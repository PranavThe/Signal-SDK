from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, require_api_key
from api.config import settings
from api.dashboard_auth import require_dashboard_org_auth
from api.database import get_session
from api.models import ConsolidationSuggestion, Escalation, Rule
from api.services.embedding_service import embed, save_rule_embedding
from api.services.escalation_pipeline import prepare_escalation_semantics
from api.services.lifecycle_service import run_consolidation, run_staleness_check
from api.services.webhook_service import send_webhook_event_by_org_id


router = APIRouter(tags=["lifecycle"])
logger = logging.getLogger(__name__)


@router.post("/admin/lifecycle/run-staleness")
async def trigger_staleness_check(
    include_new_rules: bool = False,
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, int]:
    _ = auth
    return await run_staleness_check(include_new_rules=include_new_rules)


@router.post("/admin/lifecycle/run-consolidation")
async def trigger_consolidation(
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, int]:
    return await run_consolidation(org_id=auth.org_id)


@router.post("/admin/diagnostics/embedding")
async def diagnose_embedding(
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    _ = auth
    try:
        embedding = await embed("Signal embedding diagnostic")
    except Exception as exc:
        return {
            "ok": False,
            "voyage_configured": bool(settings.voyage_api_key),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
    return {
        "ok": True,
        "voyage_configured": bool(settings.voyage_api_key),
        "dimensions": len(embedding),
    }


@router.post("/admin/diagnostics/escalations/{escalation_id}/semantics")
async def diagnose_escalation_semantics(
    escalation_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    escalation = (
        await session.execute(
            select(Escalation).where(
                Escalation.id == escalation_id,
                Escalation.org_id == auth.org_id,
            )
        )
    ).scalar_one_or_none()
    if escalation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found")

    try:
        similar = await prepare_escalation_semantics(str(escalation.id), raise_errors=True)
    except Exception as exc:
        return {
            "ok": False,
            "voyage_configured": bool(settings.voyage_api_key),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }

    await session.refresh(escalation)
    return {
        "ok": escalation.context_embedding is not None,
        "voyage_configured": bool(settings.voyage_api_key),
        "embedding_saved": escalation.context_embedding is not None,
        "similar_decision_count": len(similar),
    }


async def _accept_consolidation_suggestion(
    suggestion_id: UUID,
    session: AsyncSession,
    auth: AuthContext,
) -> dict[str, str]:
    suggestion = (
        await session.execute(
            select(ConsolidationSuggestion).where(
                ConsolidationSuggestion.id == suggestion_id,
                ConsolidationSuggestion.org_id == auth.org_id,
                ConsolidationSuggestion.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if suggestion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")

    rule_a = await session.get(Rule, suggestion.rule_a_id)
    rule_b = await session.get(Rule, suggestion.rule_b_id)
    if rule_a is None or rule_b is None or rule_a.org_id != auth.org_id or rule_b.org_id != auth.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion rules not found")

    merged_rule = Rule(
        org_id=auth.org_id,
        condition_description=suggestion.merged_condition,
        action_description=suggestion.merged_action,
        exceptions_note="",
        structured_conditions=_merge_structured_conditions(rule_a, rule_b),
        structured_action=_merge_structured_action(rule_a, rule_b, suggestion.merged_action),
        agent_scope=_merge_agent_scope(rule_a, rule_b),
        extraction_confidence=min(rule_a.extraction_confidence, rule_b.extraction_confidence, 0.75),
        status="active",
    )
    session.add(merged_rule)
    await session.flush()

    try:
        embedding = await embed(merged_rule.condition_description)
        await save_rule_embedding(session, str(merged_rule.id), embedding)
    except Exception:
        logger.exception("Could not embed merged rule %s", merged_rule.id)

    now = datetime.now(UTC)
    rule_a.status = "archived"
    rule_b.status = "archived"
    rule_a.updated_at = now
    rule_b.updated_at = now
    suggestion.status = "accepted"
    await session.commit()

    await send_webhook_event_by_org_id(
        auth.org_id,
        "rule.created",
        {
            "id": str(merged_rule.id),
            "org_id": str(auth.org_id),
            "condition_description": merged_rule.condition_description,
            "action_description": merged_rule.action_description,
            "status": merged_rule.status,
            "merged_from_rule_ids": [str(rule_a.id), str(rule_b.id)],
            "created_at": merged_rule.created_at,
        },
    )

    return {
        "suggestion_id": str(suggestion.id),
        "merged_rule_id": str(merged_rule.id),
        "status": suggestion.status,
    }


async def _dismiss_consolidation_suggestion(
    suggestion_id: UUID,
    session: AsyncSession,
    auth: AuthContext,
) -> dict[str, str]:
    suggestion = (
        await session.execute(
            select(ConsolidationSuggestion).where(
                ConsolidationSuggestion.id == suggestion_id,
                ConsolidationSuggestion.org_id == auth.org_id,
                ConsolidationSuggestion.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if suggestion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")

    suggestion.status = "dismissed"
    await session.commit()

    return {
        "suggestion_id": str(suggestion.id),
        "status": suggestion.status,
    }


@router.post("/v1/consolidation/{suggestion_id}/accept")
async def accept_consolidation_suggestion(
    suggestion_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, str]:
    return await _accept_consolidation_suggestion(suggestion_id, session, auth)


@router.post("/v1/consolidation/{suggestion_id}/dismiss")
async def dismiss_consolidation_suggestion(
    suggestion_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, str]:
    return await _dismiss_consolidation_suggestion(suggestion_id, session, auth)


@router.post("/v1/consolidation/{suggestion_id}/decline")
async def decline_consolidation_suggestion(
    suggestion_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, str]:
    return await _dismiss_consolidation_suggestion(suggestion_id, session, auth)


@router.post("/admin/consolidation/{suggestion_id}/accept")
async def accept_dashboard_consolidation_suggestion(
    suggestion_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
) -> dict[str, str]:
    return await _accept_consolidation_suggestion(suggestion_id, session, auth)


@router.post("/admin/consolidation/{suggestion_id}/dismiss")
async def dismiss_dashboard_consolidation_suggestion(
    suggestion_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
) -> dict[str, str]:
    return await _dismiss_consolidation_suggestion(suggestion_id, session, auth)


@router.post("/admin/consolidation/{suggestion_id}/decline")
async def decline_dashboard_consolidation_suggestion(
    suggestion_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
) -> dict[str, str]:
    return await _dismiss_consolidation_suggestion(suggestion_id, session, auth)


def _merge_structured_conditions(rule_a: Rule, rule_b: Rule) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for condition in [*rule_a.structured_conditions, *rule_b.structured_conditions]:
        key = repr(sorted(condition.items()))
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(condition))
    return merged


def _merge_structured_action(rule_a: Rule, rule_b: Rule, merged_action: str) -> dict[str, Any]:
    if rule_a.structured_action == rule_b.structured_action:
        return dict(rule_a.structured_action)
    action = dict(rule_a.structured_action or {})
    action.setdefault("action", "proceed")
    parameters = dict(action.get("parameters") or {})
    parameters["merged_action_description"] = merged_action
    action["parameters"] = parameters
    if isinstance(action.get("outcome"), dict):
        outcome = dict(action["outcome"])
        outcome_parameters = dict(outcome.get("parameters") or {})
        outcome_parameters["merged_action_description"] = merged_action
        outcome["parameters"] = outcome_parameters
        action["outcome"] = outcome
    return action


def _merge_agent_scope(rule_a: Rule, rule_b: Rule) -> list[str]:
    if not rule_a.agent_scope or not rule_b.agent_scope:
        return []
    return sorted(set(rule_a.agent_scope).union(rule_b.agent_scope))

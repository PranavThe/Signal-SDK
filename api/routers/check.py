from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, require_api_key
from api.database import get_session
from api.models import PolicyCheckLog, Rule
from api.rate_limit import limiter
from api.rule_engine import conflicting_actions, matching_rules_for_context, most_specific_rules, rule_precedence_key
from api.schemas import CheckRequest, CheckResponse
from api.services.context_schema_service import ContextSchemaService
from api.services.embedding_service import embed
from api.services.semantic_service import find_semantic_rule_match, semantic_policy_text
from api.services.webhook_service import send_rule_triggered_webhook_by_org_id


router = APIRouter(prefix="/v1/check", tags=["check"])
logger = logging.getLogger(__name__)


@router.post("", response_model=CheckResponse)
@limiter.limit("1000/minute")
async def check_policy(
    request: Request,
    response: Response,
    payload: CheckRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> CheckResponse:
    context_result = await ContextSchemaService().normalize(
        session,
        auth.org_id,
        payload.context,
        learn=True,
        source="check",
    )
    normalized_context = context_result.normalized
    rules = (
        await session.execute(
            select(Rule).where(
                Rule.status == "active",
                Rule.org_id == auth.org_id,
            )
        )
    ).scalars().all()

    # Normalize rule condition values to match current schema types
    schema_service = ContextSchemaService()
    normalized_rules = []
    for rule in rules:
        normalized_rule = await schema_service.normalize_rule_for_matching(session, auth.org_id, rule)
        normalized_rules.append(normalized_rule)

    exact_candidates = most_specific_rules(matching_rules_for_context(normalized_rules, normalized_context, payload.agent_id))
    has_rule_conflict = conflicting_actions(exact_candidates)
    matched_rule = None
    semantic_similarity: float | None = None
    conflict_rule_ids = [str(rule.id) for rule in exact_candidates] if has_rule_conflict else []

    if exact_candidates and not has_rule_conflict:
        matched_rule = max(exact_candidates, key=rule_precedence_key)

    if matched_rule is None and not has_rule_conflict:
        try:
            semantic_text = semantic_policy_text(payload.action, normalized_context)
            semantic_match = await find_semantic_rule_match(
                session,
                await embed(semantic_text),
                str(auth.org_id),
                payload.agent_id,
                query_text=semantic_text,
            )
            if semantic_match is not None:
                matched_rule, semantic_similarity = semantic_match
        except Exception:
            logger.exception("Semantic rule match failed")

    if has_rule_conflict:
        result = "escalate"
        rule_id = None
        reasoning = (
            "Conflicting active rules matched this context, so Signal will not choose automatically. "
            f"Matching rule IDs: {', '.join(conflict_rule_ids)}"
        )
        modification = None
    elif matched_rule is None:
        result = "proceed"
        rule_id = None
        reasoning = "No applicable rule found. Proceeding with default behavior."
        modification = None
    else:
        action = matched_rule.structured_action or {}
        result = str(action.get("action", "proceed"))
        rule_id = matched_rule.id
        if semantic_similarity is not None:
            reasoning = f"Semantically matched rule ({semantic_similarity * 100:.0f}%): {matched_rule.action_description}"
        else:
            reasoning = f"Matched rule: {matched_rule.action_description}"
        modification = action.get("parameters") if result == "modify" else None

        # Atomic update to prevent race condition on trigger_count
        await session.execute(
            update(Rule)
            .where(Rule.id == matched_rule.id)
            .values(
                trigger_count=Rule.trigger_count + 1,
                last_triggered_at=datetime.now(UTC),
            )
        )

    check_log = PolicyCheckLog(
        agent_id=payload.agent_id,
        action=payload.action,
        context=payload.context,
        normalized_context=normalized_context,
        result=result,
        org_id=auth.org_id,
        rule_id=rule_id,
        reasoning=reasoning,
        cache_hit=False,
    )
    session.add(check_log)
    await session.flush()
    await session.commit()

    if matched_rule is not None:
        background_tasks.add_task(
            send_rule_triggered_webhook_by_org_id,
            auth.org_id,
            matched_rule.id,
            {
                "rule_id": str(matched_rule.id),
                "policy_check_log_id": str(check_log.id),
                "agent_id": payload.agent_id,
                "action": payload.action,
                "context": payload.context,
                "normalized_context": normalized_context,
                "result": result,
                "reasoning": reasoning,
                "trigger_count": matched_rule.trigger_count,
            },
        )

    return CheckResponse(
        result=result,
        rule_id=rule_id,
        reasoning=reasoning,
        modification=modification,
        context_warnings=context_result.warnings,
    )

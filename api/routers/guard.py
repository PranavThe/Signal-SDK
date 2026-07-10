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
from api.schemas import GuardDecision, GuardRequest
from api.services.context_schema_service import ContextSchemaService
from api.services.embedding_service import embed
from api.services.guard_decision_service import (
    allow_guard_decision,
    conflict_guard_decision,
    decision_payload,
    guard_decision_from_rule,
)
from api.services.semantic_service import find_semantic_rule_match, semantic_policy_text
from api.services.webhook_service import send_rule_triggered_webhook_by_org_id


router = APIRouter(prefix="/v1/guard", tags=["guard"])
logger = logging.getLogger(__name__)


@router.post("", response_model=GuardDecision)
@limiter.limit("1000/minute")
async def guard_action(
    request: Request,
    response: Response,
    payload: GuardRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> GuardDecision:
    schema_service = ContextSchemaService()
    context_dict = dict(payload.context)
    user_schema = context_dict.pop("_signal_schema", None)
    if user_schema and isinstance(user_schema, list):
        await schema_service.sync_user_schema(session, auth.org_id, user_schema)
        await session.flush()

    context_result = await schema_service.normalize(
        session,
        auth.org_id,
        context_dict,
        learn=True,
        source="guard",
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

    normalized_rules = [
        await schema_service.normalize_rule_for_matching(session, auth.org_id, rule)
        for rule in rules
    ]
    exact_candidates = most_specific_rules(
        matching_rules_for_context(normalized_rules, normalized_context, payload.agent_id)
    )
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
                candidate_rule, semantic_similarity = semantic_match
                from api.rule_engine import rule_matches

                if rule_matches(candidate_rule, normalized_context):
                    matched_rule = candidate_rule
                else:
                    logger.info(
                        "Semantic guard match rejected: Rule %s matched semantically (%.0f%%) "
                        "but structured conditions did not match.",
                        candidate_rule.id,
                        semantic_similarity * 100,
                    )
                    semantic_similarity = None
        except Exception:
            logger.exception("Semantic guard match failed")

    if has_rule_conflict:
        decision = conflict_guard_decision(conflict_rule_ids, context_warnings=context_result.warnings)
    elif matched_rule is None:
        decision = allow_guard_decision(
            internal_reason="No applicable rule found. Proceeding with default behavior.",
            context_warnings=context_result.warnings,
        )
    else:
        internal_reason = (
            f"Semantically matched rule ({semantic_similarity * 100:.0f}%): {matched_rule.action_description}"
            if semantic_similarity is not None
            else f"Matched rule: {matched_rule.action_description}"
        )
        decision = guard_decision_from_rule(
            matched_rule,
            action_name=payload.action,
            internal_reason=internal_reason,
            context=normalized_context,
            context_warnings=context_result.warnings,
        )
        await session.execute(
            update(Rule)
            .where(Rule.id == matched_rule.id)
            .values(
                trigger_count=Rule.trigger_count + 1,
                last_triggered_at=datetime.now(UTC),
            )
        )

    payload_dict = decision_payload(decision)
    check_log = PolicyCheckLog(
        agent_id=payload.agent_id,
        action=payload.action,
        context=payload.context,
        normalized_context=normalized_context,
        result=decision.decision,
        org_id=auth.org_id,
        rule_id=decision.rule_id,
        reasoning=decision.internal_reason,
        decision_payload=payload_dict,
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
                "decision": payload_dict,
                "trigger_count": matched_rule.trigger_count,
            },
        )

    return decision

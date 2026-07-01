from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Rule
from api.services.embedding_service import vector_literal


SEMANTIC_RULE_MATCH_THRESHOLD = 0.35
SEMANTIC_RULE_STRONG_MATCH_THRESHOLD = 0.42
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _flatten_context_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        values: list[str] = []
        for key, item in value.items():
            flattened = " ".join(_flatten_context_values(item))
            if flattened:
                values.append(f"{key}: {flattened}")
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_flatten_context_values(item))
        return values
    if value is None:
        return []
    return [str(value)]


def semantic_policy_text(action: str, context: dict[str, Any]) -> str:
    values = "; ".join(_flatten_context_values(context))
    return f"Policy check action: {action}\nSituation: {values}"


def semantic_escalation_text(context: str, metadata: dict[str, Any]) -> str:
    values = "; ".join(_flatten_context_values(metadata))
    return f"Escalation context: {context}\nSituation: {values}"


def _meaningful_tokens(text_value: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text_value.lower().replace("_", " ")) if len(token) >= 4}


def _has_enough_overlap(query_text: str, rule_text: str, similarity: float) -> bool:
    if similarity >= SEMANTIC_RULE_STRONG_MATCH_THRESHOLD:
        return True
    return len(_meaningful_tokens(query_text) & _meaningful_tokens(rule_text)) >= 2


def semantic_candidate_is_plausible(
    query_text: str,
    condition_description: str,
    action_description: str,
    similarity: float,
) -> bool:
    return _has_enough_overlap(query_text, f"{condition_description} {action_description}", similarity)


async def find_similar_escalations(
    session: AsyncSession,
    embedding: list[float],
    escalation_id: str,
    org_id: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    e.context,
                    e.human_decision,
                    e.responded_at,
                    1 - (e.context_embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM escalations e
                WHERE e.status = 'responded'
                  AND e.id != CAST(:escalation_id AS uuid)
                  AND (CAST(:org_id AS uuid) IS NULL OR e.org_id = CAST(:org_id AS uuid))
                  AND e.context_embedding IS NOT NULL
                  AND 1 - (e.context_embedding <=> CAST(:embedding AS vector)) > 0.70
                ORDER BY similarity DESC
                LIMIT :limit
                """
            ),
            {
                "embedding": vector_literal(embedding),
                "escalation_id": escalation_id,
                "org_id": org_id,
                "limit": limit,
            },
        )
    ).mappings().all()

    return [
        {
            "context": row["context"],
            "human_decision": row["human_decision"],
            "responded_at": row["responded_at"],
            "similarity": float(row["similarity"]),
        }
        for row in rows
    ]


async def find_similar_rules(
    session: AsyncSession,
    embedding: list[float],
    rule_id: str,
    org_id: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    r.id,
                    r.condition_description,
                    r.action_description,
                    r.structured_action,
                    1 - (r.condition_embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM rules r
                WHERE r.status = 'active'
                  AND r.id != CAST(:rule_id AS uuid)
                  AND (CAST(:org_id AS uuid) IS NULL OR r.org_id = CAST(:org_id AS uuid))
                  AND r.condition_embedding IS NOT NULL
                  AND 1 - (r.condition_embedding <=> CAST(:embedding AS vector)) > 0.80
                ORDER BY similarity DESC
                LIMIT :limit
                """
            ),
            {
                "embedding": vector_literal(embedding),
                "rule_id": rule_id,
                "org_id": org_id,
                "limit": limit,
            },
        )
    ).mappings().all()

    return [
        {
            "id": row["id"],
            "condition_description": row["condition_description"],
            "action_description": row["action_description"],
            "structured_action": row["structured_action"],
            "similarity": float(row["similarity"]),
        }
        for row in rows
    ]


async def find_semantic_rule_match(
    session: AsyncSession,
    embedding: list[float],
    org_id: str,
    agent_id: str,
    query_text: str | None = None,
    threshold: float = SEMANTIC_RULE_MATCH_THRESHOLD,
) -> tuple[Rule, float] | None:
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    r.id,
                    r.condition_description,
                    r.action_description,
                    1 - (r.condition_embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM rules r
                WHERE r.status = 'active'
                  AND r.org_id = CAST(:org_id AS uuid)
                  AND r.condition_embedding IS NOT NULL
                  AND (
                      cardinality(r.agent_scope) = 0
                      OR CAST(:agent_id AS text) = ANY(r.agent_scope)
                  )
                  AND 1 - (r.condition_embedding <=> CAST(:embedding AS vector)) > :threshold
                ORDER BY similarity DESC, r.trigger_count DESC, r.created_at DESC
                LIMIT 5
                """
            ),
            {
                "embedding": vector_literal(embedding),
                "org_id": org_id,
                "agent_id": agent_id,
                "threshold": threshold,
            },
        )
    ).mappings().all()

    for row in rows:
        similarity = float(row["similarity"])
        if query_text and not _has_enough_overlap(
            query_text,
            f"{row['condition_description']} {row['action_description']}",
            similarity,
        ):
            continue
        rule = await session.get(Rule, UUID(str(row["id"])))
        if rule is not None:
            return rule, similarity

    return None

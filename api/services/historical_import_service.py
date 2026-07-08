from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.models import HistoricalDecisionImport, HistoricalRuleProposal, Rule
from api.services.context_schema_service import ContextSchemaService, flatten_context


logger = logging.getLogger(__name__)


@dataclass
class PreparedDecision:
    context: dict[str, Any]
    normalized_context: dict[str, Any]
    decision: str
    action: str
    source: dict[str, Any]


def _decision_from_record(record: dict[str, Any]) -> str:
    for key in ("decision", "human_decision", "outcome", "result"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    approved = record.get("approved")
    if isinstance(approved, bool):
        return "approve" if approved else "reject"
    return str(record.get("action") or "proceed")


def _action_from_decision(decision: str, record: dict[str, Any]) -> dict[str, Any]:
    text = decision.lower()
    if any(token in text for token in ("reject", "block", "deny", "skip", "false", "no")):
        return {"action": "block", "parameters": {}}
    if "modify" in text:
        return {"action": "modify", "parameters": {}}
    if "escalate" in text:
        return {"action": "escalate", "parameters": {}}
    return {"action": "proceed", "parameters": {}}


def _context_from_record(record: dict[str, Any]) -> dict[str, Any]:
    if isinstance(record.get("context"), dict):
        return dict(record["context"])
    if isinstance(record.get("metadata"), dict):
        return dict(record["metadata"])
    ignored = {
        "decision",
        "human_decision",
        "outcome",
        "result",
        "approved",
        "action",
        "created_at",
        "timestamp",
        "id",
    }
    return {key: value for key, value in record.items() if key not in ignored}


def _condition_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.loads(json.dumps(value, default=str))


def _humanize_field(field: str) -> str:
    return field.replace(".", " ")


class HistoricalImportService:
    def __init__(self) -> None:
        self.context_schema = ContextSchemaService()
        self.client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=httpx.Timeout(90.0, connect=10.0),
        )

    async def import_records(
        self,
        session: AsyncSession,
        org_id: UUID,
        records: list[dict[str, Any]],
        *,
        filename: str = "historical-decisions",
        max_proposals: int = 8,
    ) -> HistoricalDecisionImport:
        prepared: list[PreparedDecision] = []
        fields_created = 0
        for record in records[:1000]:
            if not isinstance(record, dict):
                continue
            context = _context_from_record(record)
            if not context:
                continue
            result = await self.context_schema.normalize(
                session,
                org_id,
                context,
                learn=True,
                source="historical_import",
            )
            fields_created += len([warning for warning in result.warnings if "canonical field" in warning])
            decision = _decision_from_record(record)
            prepared.append(
                PreparedDecision(
                    context=context,
                    normalized_context=result.normalized,
                    decision=decision,
                    action=str(record.get("action") or decision),
                    source=record,
                )
            )

        import_record = HistoricalDecisionImport(
            org_id=org_id,
            filename=filename or "historical-decisions",
            status="completed",
            rows_count=len(prepared),
            fields_created=fields_created,
            proposals_created=0,
            summary="",
        )
        session.add(import_record)
        await session.flush()

        proposals = await self._propose_rules(prepared, max_proposals=max_proposals)
        for proposal in proposals:
            conditions, _ = await self.context_schema.canonicalize_conditions(
                session,
                org_id,
                proposal["structured_conditions"],
                learn=True,
                source="historical_rule",
            )
            session.add(
                HistoricalRuleProposal(
                    org_id=org_id,
                    import_id=import_record.id,
                    condition_description=proposal["condition_description"],
                    action_description=proposal["action_description"],
                    exceptions_note=proposal.get("exceptions_note", ""),
                    structured_conditions=conditions,
                    structured_action=proposal["structured_action"],
                    confidence=float(proposal.get("confidence") or 0.0),
                    evidence_count=int(proposal.get("evidence_count") or 0),
                    evidence=proposal.get("evidence") or [],
                    status="pending",
                )
            )

        import_record.proposals_created = len(proposals)
        import_record.summary = (
            f"Imported {len(prepared)} historical decisions, learned canonical fields, "
            f"and created {len(proposals)} rule proposal{'' if len(proposals) == 1 else 's'}."
        )
        await session.flush()
        return import_record

    async def _propose_rules(self, prepared: list[PreparedDecision], max_proposals: int) -> list[dict[str, Any]]:
        if not prepared:
            return []
        try:
            proposals = await self._propose_rules_with_claude(prepared, max_proposals)
            if proposals:
                return proposals[:max_proposals]
        except Exception:
            logger.exception("Historical AI rule proposal failed; falling back to deterministic proposals")
        return self._propose_rules_deterministically(prepared, max_proposals)

    async def _propose_rules_with_claude(
        self,
        prepared: list[PreparedDecision],
        max_proposals: int,
    ) -> list[dict[str, Any]]:
        examples = [
            {
                "context": item.normalized_context,
                "decision": item.decision,
                "action": item.action,
            }
            for item in prepared[:80]
        ]
        prompt = f"""You are helping configure Signal, a system that turns historic human decisions into reviewable automation rules.

Given historical decisions with canonical context fields, propose up to {max_proposals} high-precision rules.
Only propose a rule if the evidence supports a consistent human decision. Prefer narrow rules with clear exceptions.

Return JSON only:
{{
  "proposals": [
    {{
      "condition_description": "...",
      "action_description": "...",
      "exceptions_note": "...",
      "structured_conditions": [
        {{"field": "canonical.field", "operator": "eq", "value": "example"}}
      ],
      "structured_action": {{"action": "proceed|block|escalate|modify", "parameters": {{}}}},
      "confidence": 0.0,
      "evidence_count": 12,
      "evidence": [{{"decision": "...", "context": {{}}}}]
    }}
  ]
}}

Historical decisions:
{json.dumps(examples, indent=2, default=str)}"""

        message = await self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "\n".join(
            getattr(block, "text", "") if getattr(block, "type", None) == "text" else ""
            for block in message.content
        )
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return []
        data = json.loads(text[start : end + 1])
        return [proposal for proposal in data.get("proposals", []) if self._valid_proposal(proposal)]

    def _propose_rules_deterministically(
        self,
        prepared: list[PreparedDecision],
        max_proposals: int,
    ) -> list[dict[str, Any]]:
        by_decision: dict[str, list[PreparedDecision]] = defaultdict(list)
        for item in prepared:
            by_decision[item.decision.lower()].append(item)

        proposals: list[dict[str, Any]] = []
        for decision, items in sorted(by_decision.items(), key=lambda pair: len(pair[1]), reverse=True):
            if len(items) < 2:
                continue
            field_values: dict[str, Counter] = defaultdict(Counter)
            for item in items:
                for field, value in item.normalized_context.items():
                    if isinstance(value, (dict, list)):
                        continue
                    field_values[field][_condition_value(value)] += 1

            conditions = []
            for field, counts in sorted(field_values.items(), key=lambda pair: pair[1].most_common(1)[0][1], reverse=True):
                value, count = counts.most_common(1)[0]
                if count < max(2, int(len(items) * 0.65)):
                    continue
                conditions.append({"field": field, "operator": "eq", "value": value})
                if len(conditions) >= 3:
                    break
            if not conditions:
                continue

            action = _action_from_decision(decision, items[0].source)
            readable_conditions = ", ".join(
                f"{_humanize_field(condition['field'])} is {condition['value']}" for condition in conditions
            )
            evidence = [
                {"decision": item.decision, "context": item.normalized_context}
                for item in items[:5]
            ]
            proposals.append(
                {
                    "condition_description": f"When {readable_conditions}",
                    "action_description": f"Follow the historical decision pattern: {decision}",
                    "exceptions_note": "Escalate if new context contains materially different risk signals.",
                    "structured_conditions": conditions,
                    "structured_action": action,
                    "confidence": min(0.95, len(items) / max(len(prepared), 1) + 0.45),
                    "evidence_count": len(items),
                    "evidence": evidence,
                }
            )
            if len(proposals) >= max_proposals:
                break
        return proposals

    def _valid_proposal(self, proposal: dict[str, Any]) -> bool:
        if not proposal.get("condition_description") or not proposal.get("action_description"):
            return False
        if not isinstance(proposal.get("structured_conditions"), list) or not proposal["structured_conditions"]:
            return False
        action = proposal.get("structured_action") or {}
        return action.get("action") in {"proceed", "block", "escalate", "modify"}

    async def accept_proposal(
        self,
        session: AsyncSession,
        proposal: HistoricalRuleProposal,
    ) -> Rule:
        rule = Rule(
            org_id=proposal.org_id,
            condition_description=proposal.condition_description,
            action_description=proposal.action_description,
            exceptions_note=proposal.exceptions_note,
            structured_conditions=proposal.structured_conditions,
            structured_action=proposal.structured_action,
            agent_scope=[],
            extraction_confidence=proposal.confidence,
            status="active",
        )
        session.add(rule)
        proposal.status = "accepted"
        await session.flush()
        return rule

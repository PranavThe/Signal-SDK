from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Rule

logger = logging.getLogger(__name__)


@dataclass
class ExportedRule:
    condition_description: str
    action_description: str
    exceptions_note: str
    structured_conditions: list[dict[str, Any]]
    structured_action: dict[str, Any]
    agent_scope: list[str]
    status: str
    extraction_confidence: float


@dataclass
class ImportResult:
    success: bool
    imported_count: int
    skipped_count: int
    error_count: int
    errors: list[str]
    imported_rule_ids: list[str]


class RuleImportExportService:
    async def export_rules_json(
        self,
        session: AsyncSession,
        org_id: UUID,
        rule_ids: list[UUID] | None = None,
    ) -> str:
        """Export rules to JSON format."""
        query = select(Rule).where(Rule.org_id == org_id)

        if rule_ids:
            query = query.where(Rule.id.in_(rule_ids))

        result = await session.execute(query.order_by(Rule.created_at))
        rules = result.scalars().all()

        exported_data = {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "org_id": str(org_id),
            "rules": [
                {
                    "id": str(rule.id),
                    "condition_description": rule.condition_description,
                    "action_description": rule.action_description,
                    "exceptions_note": rule.exceptions_note,
                    "structured_conditions": rule.structured_conditions,
                    "structured_action": rule.structured_action,
                    "agent_scope": rule.agent_scope,
                    "status": rule.status,
                    "extraction_confidence": rule.extraction_confidence,
                    "trigger_count": rule.trigger_count,
                    "override_count": rule.override_count,
                    "created_at": rule.created_at.isoformat() if rule.created_at else None,
                    "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
                }
                for rule in rules
            ],
        }

        return json.dumps(exported_data, indent=2)

    async def export_rules_csv(
        self,
        session: AsyncSession,
        org_id: UUID,
        rule_ids: list[UUID] | None = None,
    ) -> str:
        """Export rules to CSV format."""
        query = select(Rule).where(Rule.org_id == org_id)

        if rule_ids:
            query = query.where(Rule.id.in_(rule_ids))

        result = await session.execute(query.order_by(Rule.created_at))
        rules = result.scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "ID",
            "Condition Description",
            "Action Description",
            "Exceptions Note",
            "Action Decision",
            "Status",
            "Confidence",
            "Trigger Count",
            "Override Count",
            "Created At",
        ])

        # Write data
        for rule in rules:
            writer.writerow([
                str(rule.id),
                rule.condition_description,
                rule.action_description,
                rule.exceptions_note,
                rule.structured_action.get("action", ""),
                rule.status,
                rule.extraction_confidence,
                rule.trigger_count,
                rule.override_count,
                rule.created_at.isoformat() if rule.created_at else "",
            ])

        return output.getvalue()

    async def import_rules_json(
        self,
        session: AsyncSession,
        org_id: UUID,
        json_data: str,
        skip_duplicates: bool = True,
    ) -> ImportResult:
        """Import rules from JSON format."""
        errors = []
        imported_rule_ids = []
        imported_count = 0
        skipped_count = 0
        error_count = 0

        try:
            data = json.loads(json_data)
        except json.JSONDecodeError as e:
            return ImportResult(
                success=False,
                imported_count=0,
                skipped_count=0,
                error_count=1,
                errors=[f"Invalid JSON: {str(e)}"],
                imported_rule_ids=[],
            )

        if "rules" not in data:
            return ImportResult(
                success=False,
                imported_count=0,
                skipped_count=0,
                error_count=1,
                errors=["Invalid format: missing 'rules' key"],
                imported_rule_ids=[],
            )

        for i, rule_data in enumerate(data["rules"]):
            try:
                # Validate required fields
                required_fields = [
                    "condition_description",
                    "action_description",
                    "structured_conditions",
                    "structured_action",
                ]
                missing_fields = [f for f in required_fields if f not in rule_data]
                if missing_fields:
                    error_count += 1
                    errors.append(f"Rule {i}: Missing fields: {', '.join(missing_fields)}")
                    continue

                # Check for duplicates if requested
                if skip_duplicates:
                    existing = await self._find_duplicate(
                        session,
                        org_id,
                        rule_data["condition_description"],
                        rule_data["action_description"],
                    )
                    if existing:
                        skipped_count += 1
                        continue

                # Create new rule
                new_rule = Rule(
                    org_id=org_id,
                    condition_description=rule_data["condition_description"],
                    action_description=rule_data["action_description"],
                    exceptions_note=rule_data.get("exceptions_note", ""),
                    structured_conditions=rule_data["structured_conditions"],
                    structured_action=rule_data["structured_action"],
                    agent_scope=rule_data.get("agent_scope", []),
                    status=rule_data.get("status", "pending_approval"),
                    extraction_confidence=rule_data.get("extraction_confidence", 0.0),
                )
                session.add(new_rule)
                await session.flush()

                imported_rule_ids.append(str(new_rule.id))
                imported_count += 1

            except Exception as e:
                error_count += 1
                errors.append(f"Rule {i}: {str(e)}")
                logger.exception(f"Error importing rule {i}")

        if imported_count > 0:
            await session.commit()

        return ImportResult(
            success=error_count == 0,
            imported_count=imported_count,
            skipped_count=skipped_count,
            error_count=error_count,
            errors=errors,
            imported_rule_ids=imported_rule_ids,
        )

    async def _find_duplicate(
        self,
        session: AsyncSession,
        org_id: UUID,
        condition_description: str,
        action_description: str,
    ) -> Rule | None:
        """Find a rule with matching condition and action descriptions."""
        result = await session.execute(
            select(Rule)
            .where(
                Rule.org_id == org_id,
                Rule.condition_description == condition_description,
                Rule.action_description == action_description,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

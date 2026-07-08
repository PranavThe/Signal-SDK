"""Context validation and normalization service."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import ContextField, ContextFieldAlias, Escalation, PolicyCheckLog


class ContextValidator:
    """Validates and normalizes context data."""

    def __init__(self, session: AsyncSession, org_id: UUID):
        self.session = session
        self.org_id = org_id
        self._field_cache: dict[str, str] | None = None  # alias -> canonical_name

    async def _load_field_mappings(self) -> dict[str, str]:
        """Load all field aliases for this org."""
        if self._field_cache is not None:
            return self._field_cache

        aliases = (
            await self.session.execute(
                select(ContextFieldAlias, ContextField)
                .join(ContextField, ContextFieldAlias.field_id == ContextField.id)
                .where(ContextFieldAlias.org_id == self.org_id)
            )
        ).all()

        mappings: dict[str, str] = {}
        for alias, field in aliases:
            mappings[alias.alias.lower()] = field.canonical_name

        # Also add canonical names mapping to themselves
        fields = (
            await self.session.execute(
                select(ContextField).where(ContextField.org_id == self.org_id)
            )
        ).scalars().all()

        for field in fields:
            mappings[field.canonical_name.lower()] = field.canonical_name

        self._field_cache = mappings
        return mappings

    async def normalize_context(self, context_dict: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize context by mapping aliases to canonical field names.

        Example:
            {"user_email": "alice@co.com"} -> {"email": "alice@co.com"}
        """
        mappings = await self._load_field_mappings()
        normalized = {}

        for key, value in context_dict.items():
            canonical = mappings.get(key.lower(), key)  # Use canonical if known, else original
            normalized[canonical] = value

        return normalized

    async def validate_context(
        self,
        context_dict: dict[str, Any],
        normalize: bool = True,
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Validate context and return normalized version + warnings.

        Returns:
            Tuple of (normalized_context, warnings)
        """
        warnings: list[str] = []

        # Normalize if requested
        if normalize:
            original_keys = set(context_dict.keys())
            context_dict = await self.normalize_context(context_dict)
            normalized_keys = set(context_dict.keys())

            # Warn about normalized fields
            if original_keys != normalized_keys:
                for original_key in original_keys:
                    if original_key not in normalized_keys:
                        canonical = next(
                            (v for k, v in (await self._load_field_mappings()).items() if k == original_key.lower()),
                            original_key,
                        )
                        if canonical != original_key:
                            warnings.append(
                                f"Field '{original_key}' was normalized to '{canonical}'. "
                                f"Consider using '{canonical}' directly in your SDK calls."
                            )

        # Check for missing important fields
        important_fields = await self._get_important_fields()
        missing_important = [field for field in important_fields if field not in context_dict]

        if missing_important:
            examples = await self._get_field_examples(missing_important[:3])  # Show up to 3 examples
            for field in missing_important[:3]:
                example_text = f" (example: {examples.get(field, 'N/A')})" if field in examples else ""
                warnings.append(
                    f"Missing field '{field}' - this field appears in 80%+ of similar escalations{example_text}"
                )

        # Type validation
        type_warnings = await self._validate_types(context_dict)
        warnings.extend(type_warnings)

        return context_dict, warnings

    async def _get_important_fields(self) -> list[str]:
        """Get fields that appear frequently in this org's escalations."""
        # Get fields that appear in 80%+ of escalations
        fields = (
            await self.session.execute(
                select(ContextField)
                .where(
                    ContextField.org_id == self.org_id,
                    ContextField.occurrence_count >= (
                        select(func.count(Escalation.id) * 0.8)
                        .where(Escalation.org_id == self.org_id)
                        .scalar_subquery()
                    ),
                )
                .order_by(ContextField.occurrence_count.desc())
                .limit(10)
            )
        ).scalars().all()

        return [f.canonical_name for f in fields]

    async def _get_field_examples(self, field_names: list[str]) -> dict[str, str]:
        """Get example values for fields."""
        fields = (
            await self.session.execute(
                select(ContextField)
                .where(
                    ContextField.org_id == self.org_id,
                    ContextField.canonical_name.in_(field_names),
                )
            )
        ).scalars().all()

        examples = {}
        for field in fields:
            if field.sample_values:
                examples[field.canonical_name] = str(field.sample_values[0])

        return examples

    async def _validate_types(self, context_dict: dict[str, Any]) -> list[str]:
        """Validate field types match expected types."""
        warnings: list[str] = []

        # Load expected types
        fields = (
            await self.session.execute(
                select(ContextField)
                .where(
                    ContextField.org_id == self.org_id,
                    ContextField.canonical_name.in_(list(context_dict.keys())),
                )
            )
        ).scalars().all()

        field_types = {f.canonical_name: f.field_type for f in fields}

        for key, value in context_dict.items():
            expected_type = field_types.get(key)
            if not expected_type or expected_type == "unknown":
                continue

            actual_type = self._infer_type(value)

            if expected_type != actual_type and expected_type != "mixed":
                warnings.append(
                    f"Field '{key}' expected type '{expected_type}' but got '{actual_type}'. "
                    f"Value: {json.dumps(value)[:50]}"
                )

        return warnings

    @staticmethod
    def _infer_type(value: Any) -> str:
        """Infer the type of a value."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            if "@" in value:
                return "email"
            if value.startswith("http"):
                return "url"
            return "string"
        if isinstance(value, (list, tuple)):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "unknown"


async def update_context_schema(
    session: AsyncSession,
    org_id: UUID,
    context_dict: dict[str, Any],
) -> None:
    """
    Update the context schema based on observed field usage.
    Call this after each escalation creation.
    """
    for key, value in context_dict.items():
        field_type = ContextValidator._infer_type(value)

        # Try to find existing field by canonical name
        field = (
            await session.execute(
                select(ContextField)
                .where(
                    ContextField.org_id == org_id,
                    ContextField.canonical_name == key,
                )
            )
        ).scalar_one_or_none()

        if field:
            # Update existing field
            field.occurrence_count += 1

            # Add to sample values if not already there
            if value is not None and len(field.sample_values) < 5:
                sample_str = str(value)[:100]  # Truncate long values
                if sample_str not in [str(s)[:100] for s in field.sample_values]:
                    field.sample_values = field.sample_values + [sample_str]

            # Update type if it was unknown or if we see mixed types
            if field.field_type == "unknown":
                field.field_type = field_type
            elif field.field_type != field_type and field.field_type != "mixed":
                field.field_type = "mixed"
        else:
            # Create new field
            field = ContextField(
                org_id=org_id,
                canonical_name=key,
                field_type=field_type,
                sample_values=[str(value)[:100]] if value is not None else [],
                occurrence_count=1,
            )
            session.add(field)

    await session.flush()

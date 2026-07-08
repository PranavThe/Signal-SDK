from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import ContextField, ContextFieldAlias, Rule


_NON_WORD_RE = re.compile(r"[^a-zA-Z0-9]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TITLE_KV_RE = re.compile(
    r"(?:(?<=^)|(?<=[\n\r\t ]))"
    r"([A-Z][A-Za-z0-9_.-]*(?:[ \t]+[a-z][A-Za-z0-9_.-]*){0,7})"
    r"\s*[:=]\s*"
)
_MACHINE_KV_RE = re.compile(
    r"(?:(?<=^)|(?<=[\n\r\t {,]))"
    r"([a-z][a-z0-9_.-]*(?:[._-][a-z0-9_.-]+)+)"
    r"\s*[:=]\s*"
)
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d+|\d+\.\d*|\.\d+)$")
_PERSON_SCALAR_FIELDS = {
    "actor",
    "approver",
    "author",
    "creator",
    "owner",
    "requester",
    "reviewer",
    "submitter",
    "submitted.by",
    "user",
}
_DECISION_KEYS = {"decision", "human_decision", "outcome", "result", "approved", "action"}
_INVALID_INLINE_LABELS = {"http", "https", "mailto", "true", "false", "none", "null"}
_BUILTIN_CONTEXT_ALIASES_RAW = {
    "allowed pairs": "route.pair.cap",
    "allowed_pairs": "route.pair.cap",
    "departure date": "departure.date",
    "departure_date": "departure.date",
    "destination airport": "destination.airports",
    "destination airports": "destination.airports",
    "destinations": "destination.airports",
    "non stop": "nonstop.only",
    "non-stop": "nonstop.only",
    "non_stop": "nonstop.only",
    "nonstop": "nonstop.only",
    "nonstop only": "nonstop.only",
    "nonstop_only": "nonstop.only",
    "operational risk": "operational.risk",
    "origin airport": "origin.airports",
    "origin airports": "origin.airports",
    "origins": "origin.airports",
    "provider limitation": "provider.limitation",
    "provider limitations": "provider.limitation",
    "requested pairs": "requested.route.pairs",
    "requested route pairs": "requested.route.pairs",
    "requested_pairs": "requested.route.pairs",
    "return date": "return.date",
    "return_date": "return.date",
    "route pair cap": "route.pair.cap",
    "route-pair cap": "route.pair.cap",
    "route_pair_cap": "route.pair.cap",
    "route pairs requested": "requested.route.pairs",
    "routes requested per pair": "routes.requested.per.pair",
    "routes requested per route pair": "routes.requested.per.pair",
    "routes_requested_per_pair": "routes.requested.per.pair",
    "sensitive data": "sensitive.data.included",
    "sensitive data included": "sensitive.data.included",
    "trip type": "trip.type",
}


@dataclass
class ContextNormalizationResult:
    normalized: dict[str, Any]
    aliases: dict[str, str]
    warnings: list[str]
    raw_flat: dict[str, Any]


def canonicalize_field_name(field: str) -> str:
    value = str(field or "").strip()
    if not value:
        return ""
    value = _CAMEL_RE.sub(".", value)
    value = _NON_WORD_RE.sub(".", value)
    value = re.sub(r"\.+", ".", value).strip(".").lower()
    return value


def canonicalize_scalar_field(field: str) -> str:
    canonical = canonicalize_field_name(field)
    if canonical in _PERSON_SCALAR_FIELDS:
        return f"{canonical}.name"
    return canonical


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return "string"


def _jsonable_sample(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return json.loads(json.dumps(value, default=str))
    except TypeError:
        return str(value)


def _merge_value(existing: Any, incoming: Any) -> Any:
    if existing == incoming:
        return existing
    if isinstance(existing, list):
        values = list(existing)
    else:
        values = [existing]
    if incoming not in values:
        values.append(incoming)
    return values[:5]


def _looks_like_comma_list(parts: list[str]) -> bool:
    if len(parts) < 2:
        return False
    if all(" " not in part for part in parts):
        return True
    if len(parts) >= 4 and all(len(part) <= 16 and len(part.split()) <= 2 for part in parts):
        return True
    return all(re.fullmatch(r"[A-Z0-9_.-]{2,12}", part) for part in parts)


def _coerce_context_value(value_text: str) -> Any:
    text = (value_text or "").strip().strip(",").strip()
    if not text:
        return ""

    if text[:1] in {"{", "[", '"'} or text in {"true", "false", "null"}:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    scalar_text = text[:-1].strip() if text.endswith(".") and not _FLOAT_RE.fullmatch(text) else text
    lower = scalar_text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"none", "null"}:
        return None
    if _INT_RE.fullmatch(scalar_text):
        try:
            return int(scalar_text)
        except ValueError:
            pass
    if _FLOAT_RE.fullmatch(scalar_text):
        try:
            return float(scalar_text)
        except ValueError:
            pass

    parts = [part.strip() for part in text.split(",") if part.strip()]
    if _looks_like_comma_list(parts):
        return [_coerce_context_value(part) for part in parts]

    cleaned = text.strip('"').strip("'")
    if cleaned.endswith(".") and len(cleaned) > 12:
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def _looks_like_context_label(label: str) -> bool:
    raw = (label or "").strip()
    canonical = canonicalize_field_name(raw)
    if not canonical or canonical in _INVALID_INLINE_LABELS or len(canonical) > 80:
        return False
    if " " in raw and not raw[0].isupper():
        return False
    return len(canonical.split(".")) <= 8


def _inline_key_matches(text: str) -> list[re.Match[str]]:
    matches = [
        match
        for pattern in (_TITLE_KV_RE, _MACHINE_KV_RE)
        for match in pattern.finditer(text)
        if _looks_like_context_label(match.group(1))
    ]
    matches.sort(key=lambda match: (match.start(), -(match.end() - match.start())))

    selected: list[re.Match[str]] = []
    last_end = -1
    for match in matches:
        if match.start() < last_end:
            continue
        selected.append(match)
        last_end = match.end()
    return selected


def _parse_inline_key_value_text(text: str) -> dict[str, Any]:
    matches = _inline_key_matches(text)
    if len(matches) < 2:
        return {}

    parsed: dict[str, Any] = {}
    for index, match in enumerate(matches):
        key = match.group(1).strip().strip('"').strip("'")
        value_start = match.end()
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value_text = text[value_start:value_end].strip()
        if value_text:
            parsed[key] = _coerce_context_value(value_text)
    return parsed


def _flatten_value(value: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = canonicalize_field_name(str(raw_key))
            if not key:
                continue
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(item, dict):
                nested = _flatten_value(item, path)
                if nested:
                    flat.update(nested)
                else:
                    flat[path] = item
            elif isinstance(item, list):
                flat[path] = item
                for index, child in enumerate(item[:3]):
                    if isinstance(child, dict):
                        for nested_key, nested_value in _flatten_value(child, path).items():
                            flat.setdefault(nested_key, nested_value)
            else:
                scalar_path = canonicalize_scalar_field(path)
                flat[scalar_path] = item
                if scalar_path != path:
                    flat[path] = item
        return flat
    if prefix:
        flat[canonicalize_scalar_field(prefix)] = value
    return flat


def flatten_context(context: dict[str, Any]) -> dict[str, Any]:
    flattened = _flatten_value(context)
    result: dict[str, Any] = {}
    for key, value in flattened.items():
        canonical = canonicalize_scalar_field(key)
        if not canonical:
            continue
        if canonical in result:
            result[canonical] = _merge_value(result[canonical], value)
        else:
            result[canonical] = value
    return result


def parse_context_text(context: str) -> dict[str, Any]:
    text = (context or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    parsed: dict[str, Any] = {}
    for line in text.splitlines():
        trimmed = line.strip().strip(",")
        if not trimmed:
            continue
        match = re.match(r"^([^:=]{2,80})[:=]\s*(.+)$", trimmed)
        if not match:
            continue
        key = match.group(1).strip().strip('"').strip("'")
        value_text = match.group(2).strip().strip(",").strip()
        parsed[key] = _coerce_context_value(value_text)

    inline_parsed = _parse_inline_key_value_text(text)
    if len(inline_parsed) > len(parsed):
        return inline_parsed
    return parsed


def context_from_escalation_text(context: str, metadata: dict[str, Any]) -> dict[str, Any]:
    merged = parse_context_text(context)
    for key, value in (metadata or {}).items():
        if str(key).startswith("_signal_"):
            continue
        merged.setdefault(key, value)
    return merged


def generated_aliases_for_field(canonical_name: str) -> set[str]:
    aliases = {canonical_name}
    aliases.add(canonical_name.replace(".", "_"))
    aliases.add(canonical_name.replace(".", "-"))
    parts = canonical_name.split(".")
    if len(parts) > 1:
        aliases.add("".join([parts[0], *[part.title() for part in parts[1:]]]))
        if parts[-1] == "name":
            aliases.add(".".join(parts[:-1]))
            aliases.add("_".join(parts[:-1]))
    return {alias for alias in aliases if alias}


def builtin_context_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for raw_alias, raw_canonical in _BUILTIN_CONTEXT_ALIASES_RAW.items():
        canonical = canonicalize_scalar_field(raw_canonical)
        aliases[canonicalize_scalar_field(raw_alias)] = canonical
        aliases[canonicalize_scalar_field(raw_alias.replace(" ", "_"))] = canonical
        aliases[canonicalize_scalar_field(raw_alias.replace(" ", "-"))] = canonical
        aliases[canonicalize_scalar_field(canonical)] = canonical
        for generated in generated_aliases_for_field(canonical):
            aliases[canonicalize_scalar_field(generated)] = canonical
    return aliases


class ContextSchemaService:
    async def alias_map(self, session: AsyncSession, org_id: UUID) -> dict[str, str]:
        fields = (
            await session.execute(select(ContextField).where(ContextField.org_id == org_id))
        ).scalars().all()
        aliases = (
            await session.execute(select(ContextFieldAlias).where(ContextFieldAlias.org_id == org_id))
        ).scalars().all()
        by_id = {field.id: field for field in fields}
        alias_map: dict[str, str] = {}
        for field in fields:
            alias_map[canonicalize_scalar_field(field.canonical_name)] = field.canonical_name
            for generated in generated_aliases_for_field(field.canonical_name):
                alias_map[canonicalize_scalar_field(generated)] = field.canonical_name
        for alias in aliases:
            field = by_id.get(alias.field_id)
            if field is not None:
                alias_map[canonicalize_scalar_field(alias.alias)] = field.canonical_name
        alias_map.update(builtin_context_aliases())
        return alias_map

    async def normalize(
        self,
        session: AsyncSession,
        org_id: UUID,
        context: dict[str, Any],
        *,
        learn: bool = True,
        source: str = "api",
    ) -> ContextNormalizationResult:
        raw_flat = _flatten_value(context or {})
        aliases = await self.alias_map(session, org_id)
        normalized: dict[str, Any] = {}
        alias_hits: dict[str, str] = {}
        warnings: list[str] = []

        for raw_key, value in raw_flat.items():
            canonical_key = aliases.get(canonicalize_scalar_field(raw_key), canonicalize_scalar_field(raw_key))
            if canonical_key in normalized:
                normalized[canonical_key] = _merge_value(normalized[canonical_key], value)
            else:
                normalized[canonical_key] = value
            if canonical_key != raw_key:
                alias_hits[raw_key] = canonical_key

        for raw_key, canonical_key in alias_hits.items():
            warnings.append(f"Normalized context field '{raw_key}' to canonical field '{canonical_key}'.")

        if learn:
            await self.learn_fields(session, org_id, normalized, raw_flat, source=source)

        return ContextNormalizationResult(
            normalized=normalized,
            aliases=alias_hits,
            warnings=warnings,
            raw_flat=raw_flat,
        )

    async def learn_fields(
        self,
        session: AsyncSession,
        org_id: UUID,
        normalized: dict[str, Any],
        raw_flat: dict[str, Any] | None = None,
        *,
        source: str = "observed",
    ) -> int:
        existing = (
            await session.execute(select(ContextField).where(ContextField.org_id == org_id))
        ).scalars().all()
        fields_by_name = {field.canonical_name: field for field in existing}
        created = 0
        now = datetime.now(UTC)

        for field_name, value in normalized.items():
            if not field_name:
                continue
            field = fields_by_name.get(field_name)
            sample = _jsonable_sample(value)
            if field is None:
                field = ContextField(
                    org_id=org_id,
                    canonical_name=field_name,
                    field_type=_infer_type(value),
                    description=f"Observed context field '{field_name}'.",
                    sample_values=[sample],
                    occurrence_count=1,
                )
                session.add(field)
                await session.flush()
                fields_by_name[field_name] = field
                created += 1
            else:
                samples = list(field.sample_values or [])
                if sample not in samples:
                    samples.append(sample)
                field.sample_values = samples[:8]
                if field.field_type in {"unknown", "null"}:
                    field.field_type = _infer_type(value)
                field.occurrence_count += 1
                field.updated_at = now

            aliases = generated_aliases_for_field(field_name)
            if raw_flat:
                for raw_key, raw_value in raw_flat.items():
                    if raw_value == value:
                        aliases.add(raw_key)
            await self._ensure_aliases(session, org_id, field, aliases, source)

        return created

    async def _ensure_aliases(
        self,
        session: AsyncSession,
        org_id: UUID,
        field: ContextField,
        aliases: set[str],
        source: str,
    ) -> None:
        existing_aliases = set(
            (
                await session.execute(
                    select(ContextFieldAlias.alias).where(ContextFieldAlias.org_id == org_id)
                )
            ).scalars().all()
        )
        for alias in aliases:
            canonical_alias = canonicalize_field_name(alias)
            if not canonical_alias or canonical_alias in existing_aliases:
                continue
            session.add(
                ContextFieldAlias(
                    org_id=org_id,
                    field_id=field.id,
                    alias=canonical_alias,
                    source=source,
                )
            )
            existing_aliases.add(canonical_alias)

    async def canonicalize_conditions(
        self,
        session: AsyncSession,
        org_id: UUID,
        conditions: list[dict[str, Any]],
        *,
        learn: bool = True,
        source: str = "rule",
    ) -> tuple[list[dict[str, Any]], list[str]]:
        aliases = await self.alias_map(session, org_id)
        canonical_conditions: list[dict[str, Any]] = []
        warnings: list[str] = []
        field_values: dict[str, Any] = {}
        raw_values: dict[str, Any] = {}
        for condition in conditions or []:
            updated = dict(condition)
            raw_field = str(updated.get("field") or "")
            normalized_field = canonicalize_scalar_field(raw_field)
            canonical_field = aliases.get(normalized_field, normalized_field)
            if canonical_field and canonical_field != raw_field:
                warnings.append(f"Stored rule field '{raw_field}' as canonical field '{canonical_field}'.")
            updated["field"] = canonical_field
            canonical_conditions.append(updated)
            if canonical_field:
                field_values[canonical_field] = updated.get("value")
                raw_values[raw_field] = updated.get("value")

        if learn and field_values:
            await self.learn_fields(session, org_id, field_values, raw_values, source=source)
        return canonical_conditions, warnings

    async def schema_payload(self, session: AsyncSession, org_id: UUID) -> dict[str, Any]:
        fields = (
            await session.execute(
                select(ContextField)
                .where(ContextField.org_id == org_id)
                .order_by(ContextField.occurrence_count.desc(), ContextField.canonical_name.asc())
            )
        ).scalars().all()
        aliases = (
            await session.execute(select(ContextFieldAlias).where(ContextFieldAlias.org_id == org_id))
        ).scalars().all()
        rules = (
            await session.execute(select(Rule).where(Rule.org_id == org_id))
        ).scalars().all()
        usage_counts: dict[str, int] = {}
        for rule in rules:
            seen_fields = {
                str(condition.get("field") or "")
                for condition in (rule.structured_conditions or [])
                if condition.get("field")
            }
            for field_name in seen_fields:
                usage_counts[field_name] = usage_counts.get(field_name, 0) + 1
        aliases_by_field: dict[UUID, list[str]] = {}
        for alias in aliases:
            aliases_by_field.setdefault(alias.field_id, []).append(alias.alias)
        return {
            "fields": [
                {
                    "id": str(field.id),
                    "canonical_name": field.canonical_name,
                    "field_type": field.field_type,
                    "description": field.description,
                    "sample_values": field.sample_values or [],
                    "occurrence_count": field.occurrence_count,
                    "used_by_rules": usage_counts.get(field.canonical_name, 0),
                    "aliases": sorted(set(aliases_by_field.get(field.id, []))),
                    "updated_at": field.updated_at.isoformat() if field.updated_at else None,
                }
                for field in fields
            ]
        }

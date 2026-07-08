from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, require_api_key
from api.dashboard_auth import DashboardUser, require_dashboard_org_auth, require_dashboard_user
from api.database import get_session
from api.models import ContextField, ContextFieldAlias, Escalation, HistoricalDecisionImport, HistoricalRuleProposal
from api.services.historical_import_service import HistoricalImportService
from api.services.context_schema_service import (
    ContextSchemaService,
    canonicalize_field_name,
    canonicalize_scalar_field,
    context_from_escalation_text,
    generated_aliases_for_field,
)
from api.services.embedding_service import save_rule_embedding, embed
from api.services.lifecycle_service import run_consolidation
from api.background_tasks import safe_background_task


router = APIRouter(tags=["context"])


class ContextValidateRequest(BaseModel):
    context: dict[str, Any]


class HistoricalImportRequest(BaseModel):
    filename: str = "historical-decisions"
    records: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


class AliasCreateRequest(BaseModel):
    canonical_name: str
    alias: str


class ContextFieldUpsertRequest(BaseModel):
    canonical_name: str | None = None
    field_type: str = "string"
    description: str = ""
    aliases: list[str] = Field(default_factory=list, max_length=30)
    sample_values: list[Any] = Field(default_factory=list, max_length=20)


_FIELD_TYPES = {"string", "number", "integer", "boolean", "array", "object", "enum", "unknown"}


@router.get("/v1/context/schema")
async def get_api_context_schema(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    return await ContextSchemaService().schema_payload(session, auth.org_id)


@router.post("/v1/context/validate")
async def validate_api_context(
    request: ContextValidateRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    result = await ContextSchemaService().normalize(
        session,
        auth.org_id,
        request.context,
        learn=True,
        source="validation",
    )
    await session.commit()
    return {
        "normalized_context": result.normalized,
        "aliases": result.aliases,
        "warnings": result.warnings,
    }


@router.get("/admin/context/schema")
async def get_admin_context_schema(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    return await ContextSchemaService().schema_payload(session, auth.org_id)


@router.post("/admin/context/fields")
async def create_admin_context_field(
    request: ContextFieldUpsertRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    canonical_name = canonicalize_scalar_field(request.canonical_name or "")
    if not canonical_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Canonical field is required.")
    field_type = _clean_field_type(request.field_type)

    existing = (
        await session.execute(
            select(ContextField).where(
                ContextField.org_id == auth.org_id,
                ContextField.canonical_name == canonical_name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That canonical field already exists.")

    field = ContextField(
        org_id=auth.org_id,
        canonical_name=canonical_name,
        field_type=field_type,
        description=request.description.strip(),
        sample_values=_jsonable_values(request.sample_values),
        occurrence_count=0,
    )
    session.add(field)
    await session.flush()
    await _replace_aliases(session, auth.org_id, field, request.aliases)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="One of those aliases is already used.") from exc
    return await ContextSchemaService().schema_payload(session, auth.org_id)


@router.patch("/admin/context/fields/{field_id}")
async def update_admin_context_field(
    field_id: UUID,
    request: ContextFieldUpsertRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    field = (
        await session.execute(
            select(ContextField).where(ContextField.id == field_id, ContextField.org_id == auth.org_id)
        )
    ).scalar_one_or_none()
    if field is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Context field not found.")

    field.field_type = _clean_field_type(request.field_type)
    field.description = request.description.strip()
    field.sample_values = _jsonable_values(request.sample_values)
    await _replace_aliases(session, auth.org_id, field, request.aliases)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="One of those aliases is already used.") from exc
    return await ContextSchemaService().schema_payload(session, auth.org_id)


@router.post("/admin/context/learn-from-escalations")
async def learn_context_from_escalations(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    service = ContextSchemaService()
    escalations = (
        await session.execute(
            select(Escalation)
            .where(Escalation.org_id == auth.org_id)
            .order_by(Escalation.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    created = 0
    for escalation in escalations:
        context = escalation.normalized_context or context_from_escalation_text(
            escalation.context,
            escalation.metadata_ or {},
        )
        result = await service.normalize(
            session,
            auth.org_id,
            context,
            learn=True,
            source="recent_escalations",
        )
        created += len(result.normalized)
    await session.commit()
    payload = await service.schema_payload(session, auth.org_id)
    payload["message"] = (
        f"Scanned {len(escalations)} recent escalation"
        f"{'' if len(escalations) == 1 else 's'} and refreshed the context schema."
    )
    payload["observed_fields"] = created
    return payload


@router.get("/admin/history")
async def get_admin_history(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    proposals = (
        await session.execute(
            select(HistoricalRuleProposal)
            .where(HistoricalRuleProposal.org_id == auth.org_id, HistoricalRuleProposal.status == "pending")
            .order_by(HistoricalRuleProposal.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    imports = (
        await session.execute(
            select(HistoricalDecisionImport)
            .where(HistoricalDecisionImport.org_id == auth.org_id)
            .order_by(HistoricalDecisionImport.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    return {
        "proposals": [_proposal_payload(proposal) for proposal in proposals],
        "imports": [_import_payload(item) for item in imports],
    }


@router.post("/admin/context/validate")
async def validate_admin_context(
    request: ContextValidateRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    result = await ContextSchemaService().normalize(
        session,
        auth.org_id,
        request.context,
        learn=True,
        source="dashboard_validation",
    )
    await session.commit()
    return {
        "normalized_context": result.normalized,
        "aliases": result.aliases,
        "warnings": result.warnings,
    }


@router.post("/admin/history/import")
async def import_historical_decisions(
    request: HistoricalImportRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    import_record = await HistoricalImportService().import_records(
        session,
        auth.org_id,
        request.records,
        filename=request.filename,
    )
    await session.commit()
    return {
        "import": {
            "id": str(import_record.id),
            "filename": import_record.filename,
            "rows_count": import_record.rows_count,
            "fields_created": import_record.fields_created,
            "proposals_created": import_record.proposals_created,
            "summary": import_record.summary,
        }
    }


@router.post("/admin/history/proposals/{proposal_id}/accept")
async def accept_historical_proposal(
    proposal_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    proposal = await _get_org_proposal(session, proposal_id, auth.org_id)
    if proposal.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This proposal has already been handled.")
    rule = await HistoricalImportService().accept_proposal(session, proposal)
    await session.commit()
    try:
        await save_rule_embedding(session, str(rule.id), await embed(rule.condition_description))
        await session.commit()
    except Exception:
        await session.rollback()
    safe_background_task(run_consolidation(org_id=auth.org_id, max_pairs_per_org=50), "run_consolidation")
    return {"rule_id": str(rule.id), "proposal_id": str(proposal.id), "status": "accepted"}


@router.post("/admin/history/proposals/{proposal_id}/dismiss")
async def dismiss_historical_proposal(
    proposal_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    proposal = await _get_org_proposal(session, proposal_id, auth.org_id)
    proposal.status = "dismissed"
    await session.commit()
    return {"proposal_id": str(proposal.id), "status": "dismissed"}


async def _get_org_proposal(session: AsyncSession, proposal_id: UUID, org_id: UUID) -> HistoricalRuleProposal:
    proposal = (
        await session.execute(
            select(HistoricalRuleProposal).where(
                HistoricalRuleProposal.id == proposal_id,
                HistoricalRuleProposal.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal


def _proposal_payload(proposal: HistoricalRuleProposal) -> dict[str, Any]:
    return {
        "id": str(proposal.id),
        "condition_description": proposal.condition_description,
        "action_description": proposal.action_description,
        "exceptions_note": proposal.exceptions_note,
        "structured_conditions": proposal.structured_conditions,
        "structured_action": proposal.structured_action,
        "confidence": proposal.confidence,
        "evidence_count": proposal.evidence_count,
        "evidence": proposal.evidence,
        "status": proposal.status,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
    }


def _clean_field_type(field_type: str) -> str:
    cleaned = canonicalize_field_name(field_type) or "unknown"
    if cleaned not in _FIELD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Field type must be one of: {', '.join(sorted(_FIELD_TYPES))}.",
        )
    return cleaned


def _jsonable_values(values: list[Any]) -> list[Any]:
    cleaned: list[Any] = []
    for value in values[:20]:
        if isinstance(value, (str, int, float, bool)) or value is None:
            cleaned.append(value)
        else:
            cleaned.append(str(value))
    return cleaned


async def _replace_aliases(
    session: AsyncSession,
    org_id: UUID,
    field: ContextField,
    aliases: list[str],
) -> None:
    requested_aliases = {canonicalize_field_name(alias) for alias in aliases if canonicalize_field_name(alias)}
    requested_aliases.update(generated_aliases_for_field(field.canonical_name))

    conflicts = (
        await session.execute(
            select(ContextFieldAlias.alias)
            .where(
                ContextFieldAlias.org_id == org_id,
                ContextFieldAlias.alias.in_(requested_aliases),
                ContextFieldAlias.field_id != field.id,
            )
            .limit(1)
        )
    ).scalars().all()
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alias '{conflicts[0]}' is already mapped to another context field.",
        )

    await session.execute(
        delete(ContextFieldAlias).where(
            ContextFieldAlias.org_id == org_id,
            ContextFieldAlias.field_id == field.id,
        )
    )
    for alias in sorted(requested_aliases):
        session.add(
            ContextFieldAlias(
                org_id=org_id,
                field_id=field.id,
                alias=alias,
                source="manual",
            )
        )


def _import_payload(item: HistoricalDecisionImport) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "filename": item.filename,
        "status": item.status,
        "rows_count": item.rows_count,
        "fields_created": item.fields_created,
        "proposals_created": item.proposals_created,
        "summary": item.summary,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }

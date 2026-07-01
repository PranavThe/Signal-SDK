from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, hash_api_key
from api.config import settings
from api.database import get_session
from api.models import ApiKey, DashboardOrgMembership, Organization


DASHBOARD_ACCESS_COOKIE = "signal_dashboard_access_token"
DASHBOARD_API_KEY_HASH_COOKIE = "signal_dashboard_api_key_hash"
DASHBOARD_ORG_ID_COOKIE = "signal_dashboard_org_id"


@dataclass(frozen=True)
class DashboardUser:
    user_id: str
    email: str


@dataclass(frozen=True)
class DashboardOrgContext:
    org_id: UUID
    org_name: str
    api_key_id: UUID | None
    key_prefix: str


def dashboard_auth_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_anon_key)


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


async def validate_dashboard_token(token: str) -> DashboardUser:
    if not dashboard_auth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard authentication is not configured.",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.supabase_url}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": settings.supabase_anon_key,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dashboard session could not be verified.",
        ) from exc

    if response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in again.")

    data = response.json()
    email = str(data.get("email") or "").strip()
    user_id = str(data.get("id") or "").strip()
    if not email or not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in again.")
    return DashboardUser(user_id=user_id, email=email)


async def get_dashboard_user_from_request(request: Request) -> DashboardUser | None:
    token = request.cookies.get(DASHBOARD_ACCESS_COOKIE)
    if not token:
        return None
    try:
        return await validate_dashboard_token(token)
    except HTTPException:
        return None


async def require_dashboard_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> DashboardUser:
    token = _bearer_token(authorization) or request.cookies.get(DASHBOARD_ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    return await validate_dashboard_token(token)


async def get_dashboard_org_from_request(
    request: Request,
    session: AsyncSession,
    dashboard_user: DashboardUser,
) -> DashboardOrgContext | None:
    org_id_value = request.cookies.get(DASHBOARD_ORG_ID_COOKIE)
    if org_id_value:
        try:
            org_id = UUID(org_id_value)
        except ValueError:
            org_id = None
        if org_id is not None:
            membership = (
                await session.execute(
                    select(DashboardOrgMembership).where(
                        DashboardOrgMembership.org_id == org_id,
                        DashboardOrgMembership.user_id == dashboard_user.user_id,
                    )
                )
            ).scalar_one_or_none()
            if membership is not None:
                org = await session.get(Organization, org_id)
                if org is not None:
                    return DashboardOrgContext(
                        org_id=org.id,
                        org_name=org.name,
                        api_key_id=None,
                        key_prefix="",
                    )

    key_hash = request.cookies.get(DASHBOARD_API_KEY_HASH_COOKIE)
    if not key_hash:
        return None

    api_key = (
        await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    ).scalar_one_or_none()
    if api_key is None:
        return None
    org = await session.get(Organization, api_key.org_id)
    if org is None:
        return None
    return DashboardOrgContext(
        org_id=org.id,
        org_name=org.name,
        api_key_id=api_key.id,
        key_prefix=api_key.key_prefix,
    )


async def ensure_dashboard_membership(
    session: AsyncSession,
    dashboard_user: DashboardUser,
    org: Organization,
    role: str = "member",
) -> DashboardOrgMembership:
    membership = (
        await session.execute(
            select(DashboardOrgMembership).where(
                DashboardOrgMembership.org_id == org.id,
                DashboardOrgMembership.user_id == dashboard_user.user_id,
            )
        )
    ).scalar_one_or_none()
    if membership is not None:
        return membership

    membership = DashboardOrgMembership(
        org_id=org.id,
        user_id=dashboard_user.user_id,
        email=dashboard_user.email,
        role=role,
    )
    session.add(membership)
    await session.flush()
    return membership


async def select_dashboard_org(
    session: AsyncSession,
    api_key: str,
    dashboard_user: DashboardUser,
) -> DashboardOrgContext:
    key_hash = hash_api_key(api_key.strip())
    api_key_record = (
        await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    ).scalar_one_or_none()
    if api_key_record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key")
    org = await session.get(Organization, api_key_record.org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    await ensure_dashboard_membership(session, dashboard_user, org)
    return DashboardOrgContext(
        org_id=org.id,
        org_name=org.name,
        api_key_id=api_key_record.id,
        key_prefix=api_key_record.key_prefix,
    )


async def require_dashboard_org_auth(
    request: Request,
    session: AsyncSession = Depends(get_session),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> AuthContext:
    org = await get_dashboard_org_from_request(request, session, dashboard_user)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Select an organization in Settings before using this dashboard action.",
        )

    auth = AuthContext(
        org_id=org.org_id,
        api_key_id=org.api_key_id,
        key_prefix=org.key_prefix,
    )
    request.state.auth = auth
    request.state.org_id = auth.org_id
    return auth

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, hash_api_key
from api.config import settings
from api.database import get_session
from api.models import Account, ApiKey, DashboardAccountMembership, DashboardOrgMembership, Organization


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
    account_id: UUID | None
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


def _account_name_for_user(dashboard_user: DashboardUser) -> str:
    local_part = dashboard_user.email.split("@", 1)[0].strip()
    if local_part:
        return f"{local_part}'s account"
    return "Signal account"


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


async def get_dashboard_account(
    session: AsyncSession,
    dashboard_user: DashboardUser,
) -> Account | None:
    membership = (
        await session.execute(
            select(DashboardAccountMembership)
            .outerjoin(Organization, Organization.account_id == DashboardAccountMembership.account_id)
            .where(DashboardAccountMembership.user_id == dashboard_user.user_id)
            .group_by(DashboardAccountMembership.id)
            .order_by(func.count(Organization.id).desc(), DashboardAccountMembership.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if membership is None:
        return None
    return await session.get(Account, membership.account_id)


async def ensure_dashboard_account(
    session: AsyncSession,
    dashboard_user: DashboardUser,
) -> Account:
    account = await get_dashboard_account(session, dashboard_user)
    if account is not None:
        return account

    legacy_memberships = (
        await session.execute(
            select(DashboardOrgMembership, Organization)
            .join(Organization, Organization.id == DashboardOrgMembership.org_id)
            .where(DashboardOrgMembership.user_id == dashboard_user.user_id)
            .order_by(DashboardOrgMembership.created_at.asc())
        )
    ).all()

    for _membership, org in legacy_memberships:
        if org.account_id is None:
            continue
        account = await session.get(Account, org.account_id)
        if account is not None:
            session.add(
                DashboardAccountMembership(
                    account_id=account.id,
                    user_id=dashboard_user.user_id,
                    email=dashboard_user.email,
                    role="owner",
                )
            )
            await session.flush()
            return account

    org_count = len({org.id for _membership, org in legacy_memberships})
    has_paid_status = any(org.billing_status in {"active", "trialing"} for _membership, org in legacy_memberships)
    account = Account(
        name=_account_name_for_user(dashboard_user),
        owner_user_id=dashboard_user.user_id,
        owner_email=dashboard_user.email,
        plan_tier="scale" if org_count > 3 else ("pro" if has_paid_status else "free"),
        billing_status="active",
    )
    session.add(account)
    await session.flush()
    session.add(
        DashboardAccountMembership(
            account_id=account.id,
            user_id=dashboard_user.user_id,
            email=dashboard_user.email,
            role="owner",
        )
    )
    for _membership, org in legacy_memberships:
        if org.account_id is None:
            org.account_id = account.id
    await session.flush()
    return account


async def get_dashboard_org_from_request(
    request: Request,
    session: AsyncSession,
    dashboard_user: DashboardUser,
) -> DashboardOrgContext | None:
    account = await get_dashboard_account(session, dashboard_user)
    org_id_value = request.cookies.get(DASHBOARD_ORG_ID_COOKIE)
    if org_id_value and account is not None:
        try:
            org_id = UUID(org_id_value)
        except ValueError:
            org_id = None
        if org_id is not None:
            org = (
                await session.execute(
                    select(Organization).where(
                        Organization.id == org_id,
                        Organization.account_id == account.id,
                    )
                )
            ).scalar_one_or_none()
            if org is not None:
                return DashboardOrgContext(
                    org_id=org.id,
                    org_name=org.name,
                    account_id=account.id,
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
        account_id=org.account_id,
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
    if org.account_id is None:
        account = await ensure_dashboard_account(session, dashboard_user)
        org.account_id = account.id
    else:
        account = await session.get(Account, org.account_id)
        if account is not None:
            account_membership = (
                await session.execute(
                    select(DashboardAccountMembership).where(
                        DashboardAccountMembership.account_id == account.id,
                        DashboardAccountMembership.user_id == dashboard_user.user_id,
                    )
                )
            ).scalar_one_or_none()
            if account_membership is None:
                session.add(
                    DashboardAccountMembership(
                        account_id=account.id,
                        user_id=dashboard_user.user_id,
                        email=dashboard_user.email,
                        role="owner",
                    )
                )
    await ensure_dashboard_membership(session, dashboard_user, org)
    return DashboardOrgContext(
        org_id=org.id,
        org_name=org.name,
        account_id=org.account_id,
        api_key_id=api_key_record.id,
        key_prefix=api_key_record.key_prefix,
    )


async def select_dashboard_org_by_id(
    session: AsyncSession,
    org_id: UUID,
    dashboard_user: DashboardUser,
) -> DashboardOrgContext:
    account = await ensure_dashboard_account(session, dashboard_user)
    org = (
        await session.execute(
            select(Organization).where(
                Organization.id == org_id,
                Organization.account_id == account.id,
            )
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return DashboardOrgContext(
        org_id=org.id,
        org_name=org.name,
        account_id=account.id,
        api_key_id=None,
        key_prefix="",
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
            detail="Select an organization from Organizations before using this dashboard action.",
        )

    auth = AuthContext(
        org_id=org.org_id,
        api_key_id=org.api_key_id,
        key_prefix=org.key_prefix,
    )
    request.state.auth = auth
    request.state.org_id = auth.org_id
    return auth

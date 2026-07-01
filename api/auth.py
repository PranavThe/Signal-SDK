from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models import ApiKey


@dataclass(frozen=True)
class AuthContext:
    org_id: UUID
    api_key_id: UUID
    key_prefix: str


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )
    return token.strip()


async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    token = _bearer_token(authorization)
    key_hash = hash_api_key(token)
    api_key = (
        await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    ).scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )

    api_key.last_used_at = datetime.now(UTC)
    await session.commit()

    auth = AuthContext(
        org_id=api_key.org_id,
        api_key_id=api_key.id,
        key_prefix=api_key.key_prefix,
    )
    request.state.auth = auth
    request.state.org_id = auth.org_id
    return auth


ApiKeyDependency = Depends(require_api_key)

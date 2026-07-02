from __future__ import annotations

import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from api.config import settings


def api_key_rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
    return get_remote_address(request)


limiter = Limiter(
    key_func=api_key_rate_limit_key,
    default_limits=["200/minute"],
    headers_enabled=True,
    storage_uri=settings.redis_url,
    in_memory_fallback_enabled=True,
    in_memory_fallback=["200/minute"],
)

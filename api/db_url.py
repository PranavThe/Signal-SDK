from __future__ import annotations

import ssl
from typing import Any

from sqlalchemy.engine import make_url


def normalize_database_url(database_url: str) -> tuple[str, dict[str, Any]]:
    """Convert Supabase SSL query params into asyncpg connect args."""
    url = make_url(database_url)
    query = dict(url.query)
    ssl_mode = query.pop("ssl", None) or query.pop("sslmode", None)
    connect_args: dict[str, Any] = {}

    if ssl_mode:
        ssl_text = str(ssl_mode).lower()
        if ssl_text in {"require", "1", "true"}:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = ssl_context
        elif ssl_text in {"verify-ca", "verify-full"}:
            connect_args["ssl"] = True
        elif ssl_text in {"0", "false", "disable"}:
            connect_args["ssl"] = False

    clean_url = url.set(query=query)
    return clean_url.render_as_string(hide_password=False), connect_args

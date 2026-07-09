from __future__ import annotations

import os
from typing import Any

from signal_sdk.client import (
    CheckResult,
    EscalationResult,
    Field,
    Signal,
    builtin_context_aliases,
    canonicalize_field_name,
    normalize_context,
)


DEFAULT_BASE_URL = "https://signal-omega-tan.vercel.app"
__version__ = "0.2.2"

_api_key: str | None = None
_base_url: str | None = None
_dev_mode: bool = False
_auto_enrich: bool = True


def configure(
    api_key: str | None = None,
    base_url: str | None = None,
    dev_mode: bool = False,
    auto_enrich: bool = True,
) -> None:
    """Configure Signal globally.

    Args:
        api_key: Your Signal API key (can also use SIGNALOPS_API_KEY env var)
        base_url: Custom Signal deployment URL
        dev_mode: Enable debug logging for development
        auto_enrich: Automatically add timestamp and environment to context
    """
    global _api_key, _base_url, _dev_mode, _auto_enrich
    if api_key is not None:
        _api_key = api_key
    if base_url is not None:
        _base_url = base_url
    _dev_mode = dev_mode
    _auto_enrich = auto_enrich


def client(api_key: str | None = None, base_url: str | None = None) -> Signal:
    resolved_api_key = api_key or _api_key or os.getenv("SIGNALOPS_API_KEY")
    if not resolved_api_key:
        raise RuntimeError("Set SIGNALOPS_API_KEY or call signalops.configure(api_key=...).")
    resolved_base_url = base_url or _base_url or os.getenv("SIGNALOPS_BASE_URL") or DEFAULT_BASE_URL
    return Signal(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        dev_mode=_dev_mode,
        auto_enrich=_auto_enrich,
    )


async def escalate(
    context: str | dict[str, Any],
    question: str,
    agent_id: str,
    metadata: dict[str, Any] | None = None,
    action: str | None = None,
    timeout_seconds: int = 3600,
    poll_interval_seconds: int = 3,
    api_key: str | None = None,
    base_url: str | None = None,
) -> EscalationResult:
    return await client(api_key=api_key, base_url=base_url).escalate(
        context=context,
        question=question,
        agent_id=agent_id,
        metadata=metadata,
        action=action,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


async def check(
    action: str,
    context: dict[str, Any],
    agent_id: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> CheckResult:
    return await client(api_key=api_key, base_url=base_url).check(
        action=action,
        context=context,
        agent_id=agent_id,
    )


# Re-export exceptions
from signalops.exceptions import (  # noqa: E402
    SignalAuthError,
    SignalError,
    SignalNetworkError,
    SignalTimeout,
)

__all__ = [
    "CheckResult",
    "EscalationResult",
    "Field",
    "Signal",
    "SignalAuthError",
    "SignalError",
    "SignalNetworkError",
    "SignalTimeout",
    "__version__",
    "builtin_context_aliases",
    "canonicalize_field_name",
    "check",
    "client",
    "configure",
    "escalate",
    "normalize_context",
]

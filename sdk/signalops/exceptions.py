"""Signal exception types for error handling."""

from __future__ import annotations


class SignalError(Exception):
    """Base exception for all Signal errors."""
    pass


class SignalTimeout(SignalError):
    """Raised when an escalation times out waiting for a decision."""
    pass


class SignalAuthError(SignalError):
    """Raised when API authentication fails (invalid or missing API key)."""
    pass


class SignalNetworkError(SignalError):
    """Raised when network connectivity issues occur."""
    pass


__all__ = [
    "SignalError",
    "SignalTimeout",
    "SignalAuthError",
    "SignalNetworkError",
]

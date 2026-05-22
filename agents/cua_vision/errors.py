"""Shared CUA Vision runtime exceptions."""


class OpenRouterFallbackError(RuntimeError):
    """Raised when no configured vision provider responds."""

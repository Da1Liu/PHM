"""Lightweight API/domain markers.

These markers are intentionally behavior-neutral. Phase 1 keeps the same
database and runtime, but makes Edge / Cloud / Shared ownership explicit.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable


class Domain(str, Enum):
    EDGE = "Edge"
    CLOUD = "Cloud"
    SHARED = "Shared"


def tag_api(domain: Domain, purpose: str = "") -> Callable:
    """Attach domain metadata to a Flask view without changing behavior."""
    def deco(fn: Callable) -> Callable:
        setattr(fn, "api_domain", domain.value)
        setattr(fn, "api_purpose", purpose)
        return fn

    return deco


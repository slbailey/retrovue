from __future__ import annotations

from fastapi import HTTPException, Request

from ...runtime.clock import AuthoritativeClock


def get_clock(request: Request) -> AuthoritativeClock:
    """Return the app-configured authoritative clock or fail fast."""
    clock = getattr(request.app.state, "clock", None)
    if clock is None:
        raise HTTPException(status_code=500, detail="Authoritative clock not configured")
    return clock

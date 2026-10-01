"""Route iteration across FastAPI versions.

FastAPI 0.137 stopped copying included routers' routes into ``app.routes``;
it now stores a tree of included-router nodes. ``iter_route_contexts``
(FastAPI >= 0.137.2) flattens that tree into contexts that delegate to the
effective route (prefixed path, merged dependencies). Older FastAPI keeps a
flat list of routes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

try:
    from fastapi.routing import (
        iter_route_contexts as _iter_route_contexts,  # pyright: ignore[reportAttributeAccessIssue]
    )
except ImportError:  # FastAPI < 0.137: app.routes is already flat
    _iter_route_contexts = None


def iter_routes(app: Any) -> Iterable[Any]:
    """Return every route of *app*, including routes from included routers."""
    if _iter_route_contexts is None:
        return app.routes
    return _iter_route_contexts(app.routes)


def set_route_attr(route: Any, name: str, value: Any) -> None:
    """Set an attribute on a route yielded by :func:`iter_routes`.

    Writes to the user's original route, and on FastAPI >= 0.137 also to the
    cached effective route context (private ``_route_context``), which
    FastAPI copies from the original once and then reads for OpenAPI.
    """
    setattr(getattr(route, "original_route", route), name, value)
    effective = getattr(route, "_route_context", None)
    if effective is not None:
        setattr(effective, name, value)

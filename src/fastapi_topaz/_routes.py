"""Route iteration across FastAPI versions.

FastAPI 0.137 stopped copying included routers' routes into ``app.routes``;
it now stores a tree of included-router nodes. ``iter_route_contexts``
(FastAPI >= 0.137.2) flattens that tree into contexts that delegate to the
effective route (prefixed path, merged dependencies). Older FastAPI keeps a
flat list of routes.

Frontend routes (``app.frontend()`` / ``router.frontend()``) are not part of
that tree: FastAPI matches them last, through private router internals.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from starlette.routing import Match

try:
    from fastapi.routing import (
        iter_route_contexts as _iter_route_contexts,  # pyright: ignore[reportAttributeAccessIssue]
    )
except ImportError:  # FastAPI < 0.137: app.routes is already flat
    _iter_route_contexts = None

logger = logging.getLogger("fastapi_topaz.routes")


class FrontendMatchError(RuntimeError):
    """FastAPI serves frontend routes, but this FastAPI version cannot be inspected."""


@dataclass(frozen=True)
class FrontendRoute:
    """A matched frontend route; *path* is its mount path (e.g. ``/app``)."""

    path: str
    dependencies: list[Any] = field(default_factory=list)
    dependant: Any = None


def iter_routes(app: Any) -> Iterable[Any]:
    """Return every route of *app*, including routes from included routers."""
    if _iter_route_contexts is None:
        return app.routes
    return _iter_route_contexts(app.routes)


def iter_frontend_paths(app: Any) -> list[str]:
    """Return the mount paths of *app*'s frontend routes (e.g. ``/app``, ``/out/in/ui``).

    Paths have the form :func:`match_frontend_route` reports, prefixes from
    ``include_router()`` included.

    Raises:
        FrontendMatchError: The FastAPI version has frontend routes but its
            private internals are not the ones this was written for.
    """
    router = getattr(app, "router", None)
    if not hasattr(router, "frontend"):
        return []  # FastAPI without frontend routes
    try:
        from fastapi.routing import (
            _FrontendRouteGroup,  # pyright: ignore[reportAttributeAccessIssue]
        )

        paths: list[str] = []
        for candidate in router._iter_low_priority_routes():  # pyright: ignore[reportOptionalMemberAccess]
            if isinstance(candidate, _FrontendRouteGroup):
                group, prefix = candidate, ""
            else:
                group, prefix = candidate.original_route, candidate.frontend_prefix
                if not isinstance(group, _FrontendRouteGroup):
                    continue
            for route in group.routes:
                # Same rule as FastAPI's _join_frontend_paths()
                if not prefix:
                    path = route.path
                elif route.path == "/":
                    path = prefix
                else:
                    path = prefix + route.path
                if path not in paths:
                    paths.append(path)
        return paths
    except Exception as exc:
        raise FrontendMatchError(f"Cannot list FastAPI frontend routes: {exc!r}") from exc


def match_frontend_route(app: Any, scope: Any) -> FrontendRoute | None:
    """Match *scope* against *app*'s frontend routes, as FastAPI does after regular routes.

    Returns ``None`` when no frontend route matches, or when FastAPI would
    answer with a trailing-slash redirect before trying frontend routes (the
    redirected request is authorized on its own).

    Raises:
        FrontendMatchError: The FastAPI version has frontend routes but its
            private matching internals are not the ones this was written for.
    """
    router = getattr(app, "router", None)
    if not hasattr(router, "frontend"):
        return None  # FastAPI without frontend routes
    try:
        # Present wherever FastAPI has frontend routes; absent from older Starlette
        from starlette._utils import get_route_path  # pyright: ignore[reportAttributeAccessIssue]

        route_path = get_route_path(scope)
        # Mirrors APIRouter.app(): a slash redirect wins over frontend routes
        if scope.get("type") == "http" and router.redirect_slashes and route_path != "/":  # pyright: ignore[reportOptionalMemberAccess]
            redirect_scope = dict(scope)
            if route_path.endswith("/"):
                redirect_scope["path"] = redirect_scope["path"].rstrip("/")
            else:
                redirect_scope["path"] = redirect_scope["path"] + "/"
            for regular_route in router.routes:  # pyright: ignore[reportOptionalMemberAccess]
                if regular_route.matches(redirect_scope)[0] != Match.NONE:
                    return None

        matcher = getattr(router, "_match_low_priority", None)
        if matcher is None:
            raise FrontendMatchError("FastAPI router has no _match_low_priority()")
        match, child_scope, route, route_context = matcher(scope)
        if match != Match.FULL:
            return None
        # The remainder after the mount path, e.g. "x/y.js" for /app/x/y.js
        remainder = child_scope.get("fastapi", {}).get("frontend_path")
        if not isinstance(remainder, str):
            raise FrontendMatchError("FastAPI frontend match has no frontend_path")
        mount_path = route_path[: len(route_path) - len(remainder)].rstrip("/") or "/"
    except FrontendMatchError:
        raise
    except Exception as exc:
        raise FrontendMatchError(f"Cannot match FastAPI frontend routes: {exc!r}") from exc
    # The effective context carries dependencies merged from include_router()
    source = route_context if route_context is not None else route
    return FrontendRoute(
        path=mount_path,
        dependencies=list(getattr(source, "dependencies", None) or []),
        dependant=getattr(source, "dependant", None),
    )


def set_route_attr(route: Any, name: str, value: Any) -> None:
    """Set an attribute on a route yielded by :func:`iter_routes`.

    On FastAPI >= 0.137 an included route is written only on its cached
    effective route context (private ``_route_context``), which FastAPI reads
    for OpenAPI: the original route can be included more than once under
    different prefixes, each needing its own value. Other routes are written
    directly.
    """
    if hasattr(route, "original_route") and not hasattr(route, "_route_context"):
        logger.warning(
            "Unsupported FastAPI route context layout; %s set on the original route only",
            name,
        )
    effective = getattr(route, "_route_context", None)
    target = effective if effective is not None else getattr(route, "original_route", route)
    setattr(target, name, value)

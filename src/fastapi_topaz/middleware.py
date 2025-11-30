"""
Authorization middleware for FastAPI.

Provides global request-level authorization that auto-protects all routes
without requiring explicit Depends() on each endpoint.
"""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any, Callable, Literal

from aserto.client import Identity, IdentityType
from fastapi import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Match

from .dependencies import TopazConfig, _resolve_policy_path

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("fastapi_topaz.middleware")

__all__ = ["TopazMiddleware", "skip_middleware", "SkipMiddleware"]


class SkipMiddleware:
    """
    Marker dependency to skip authorization middleware for a router or route.

    Use as a dependency on a router to exclude all routes from middleware authorization:

    ```python
    from fastapi import APIRouter, Depends
    from fastapi_topaz import SkipMiddleware

    public_router = APIRouter(
        prefix="/api/public",
        dependencies=[Depends(SkipMiddleware)],
    )

    @public_router.get("/status")  # Automatically excluded from middleware
    async def public_status():
        return {"status": "ok"}
    ```
    """

    def __init__(self) -> None:
        pass


def skip_middleware(func: Callable) -> Callable:
    """
    Decorator to mark a route as excluded from authorization middleware.

    The decorated endpoint will not be checked by TopazMiddleware,
    allowing you to implement custom authorization logic.

    ```python
    from fastapi_topaz import skip_middleware

    @app.post("/documents/bulk-import")
    @skip_middleware
    async def bulk_import(
        _=Depends(require_policy_allowed(config, "myapp.admin.bulk_import")),
    ):
        # Custom policy path, not auto-generated
        ...
    ```
    """
    func.__skip_topaz_middleware__ = True  # type: ignore[attr-defined]
    return func


class TopazMiddleware:
    """
    FastAPI middleware for global authorization (pure ASGI).

    Auto-protects all routes by checking policy paths derived from HTTP method
    and route pattern. Routes are protected unless explicitly excluded.

    Args:
        app: The FastAPI application
        config: TopazConfig with authorizer settings
        exclude_paths: Regex patterns for paths to skip (e.g., [r"^/health$", r"^/docs.*"])
        exclude_methods: HTTP methods to skip (default: ["OPTIONS", "HEAD"])
        on_missing_identity: How to handle missing identity:
            - "deny": Return 401 Unauthorized
            - "anonymous": Pass anonymous identity to Topaz (let policy decide)
        on_denied: Optional callback to customize 403 response
    """

    def __init__(
        self,
        app: ASGIApp,
        config: TopazConfig,
        exclude_paths: list[str] | None = None,
        exclude_methods: list[str] | None = None,
        on_missing_identity: Literal["deny", "anonymous"] = "deny",
        on_denied: Callable[[Request, str], Response] | None = None,
    ) -> None:
        self.app = app
        self.config = config
        self.exclude_paths = [re.compile(p) for p in (exclude_paths or [])]
        self.exclude_methods = set(exclude_methods or ["OPTIONS", "HEAD"])
        self.on_missing_identity = on_missing_identity
        self.on_denied = on_denied

    def _match_route(self, scope: Scope) -> tuple[Any, dict] | None:
        """Manually match the route from the app's routes."""
        app = scope.get("app")
        if not app or not hasattr(app, "routes"):
            return None

        for route in app.routes:
            match, child_scope = route.matches(scope)
            if match == Match.FULL:
                return route, child_scope
        return None

    def _is_excluded(self, method: str, path: str, route: Any) -> bool:
        """Check if request should skip authorization."""
        if method in self.exclude_methods:
            return True

        for pattern in self.exclude_paths:
            if pattern.match(path):
                return True

        if route:
            endpoint = getattr(route, "endpoint", None)
            if endpoint and getattr(endpoint, "__skip_topaz_middleware__", False):
                return True

            dependencies = getattr(route, "dependencies", None) or []
            for dep in dependencies:
                dep_callable = getattr(dep, "dependency", None)
                if dep_callable is SkipMiddleware:
                    return True

        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "/")

        # Match route manually
        match_result = self._match_route(scope)
        route = match_result[0] if match_result else None
        path_params = match_result[1].get("path_params", {}) if match_result else {}

        # Check exclusions
        if self._is_excluded(method, path, route):
            await self.app(scope, receive, send)
            return

        # No matched route - pass through (will be 404)
        if route is None:
            await self.app(scope, receive, send)
            return

        # Generate policy path
        route_path = getattr(route, "path", path)
        policy_path = _resolve_policy_path(self.config.policy_path_root, method, route_path)

        # Create request for identity extraction
        request = Request(scope, receive)

        # Extract identity
        start_time = time.monotonic()
        try:
            identity = self.config.identity_provider(request)
        except Exception:
            identity = None

        # Handle missing identity
        if identity is None or not identity.value:
            if self.on_missing_identity == "deny":
                if self.config.audit_logger:
                    await self.config.audit_logger.log_unauthenticated_event(request, "missing_identity")
                response = JSONResponse(status_code=401, content={"detail": "Unauthorized"})
                await response(scope, receive, send)
                return
            identity = Identity(type=IdentityType.IDENTITY_TYPE_NONE, value="anonymous")

        # Build resource context
        resource_context = {}
        if self.config.resource_context_provider:
            resource_context.update(self.config.resource_context_provider(request))
        resource_context.update(path_params)

        # Check authorization
        try:
            allowed = await self.config.check_decision(
                request, policy_path, "allowed", resource_context or None
            )
        except Exception:
            allowed = False

        latency_ms = (time.monotonic() - start_time) * 1000

        # Audit logging
        if self.config.audit_logger:
            await self.config.audit_logger.log_decision(
                request=request, policy_path=policy_path, allowed=allowed, source="middleware",
                identity_type=identity.type.name if hasattr(identity.type, "name") else str(identity.type),  # type: ignore[union-attr]
                identity_value=identity.value, latency_ms=latency_ms,
                resource_context=resource_context or None,
            )

        if not allowed:
            if self.on_denied:
                response = self.on_denied(request, policy_path)
            else:
                response = JSONResponse(status_code=403, content={"detail": "Forbidden"})
            await response(scope, receive, send)
            return

        # Store path_params in scope for the handler
        scope["path_params"] = path_params
        await self.app(scope, receive, send)

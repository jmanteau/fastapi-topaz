"""
Authorization middleware for FastAPI.

Provides global request-level authorization that auto-protects all routes
without requiring explicit Depends() on each endpoint.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

from aserto.client import Identity, IdentityType
from fastapi import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Match

from ._policy import _compile_policy_groups, _resolve_policy_path, scan_policy_files
from .config import TopazConfig

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

    Policy Resolution Chain (first match wins):
      1. Explicit: Route has a ``.rego`` file in *policies_dir*
      2. Group: Route matches a :class:`PolicyGroup` ``url_pattern``
      3. Default: ``config.default_policy`` is set
      4. Generated: Use auto-generated policy path (legacy behaviour)

    Args:
        app: The FastAPI application
        config: TopazConfig with authorizer settings
        exclude_paths: Regex patterns for paths to skip (e.g., [r"^/health$", r"^/docs.*"])
        exclude_methods: HTTP methods to skip (default: ["OPTIONS", "HEAD"])
        on_missing_identity: How to handle missing identity:
            - "deny": Return 401 Unauthorized
            - "anonymous": Pass anonymous identity to Topaz (let policy decide)
        on_denied: Optional callback to customize 403 response
        on_error: How to respond when the authorization check itself fails
            (e.g. authorizer unreachable) and no circuit breaker fallback applies:
            - "deny": Return 403 Forbidden (fail-closed default)
            - "unavailable": Return 503 Service Unavailable
        policies_dir: Optional directory to scan for explicit ``.rego`` policy files
            at startup.  When provided, the middleware builds a set of known policy
            paths and uses the resolution chain to decide which policy to evaluate
            per request.
    """

    def __init__(
        self,
        app: ASGIApp,
        config: TopazConfig,
        exclude_paths: list[str] | None = None,
        exclude_methods: list[str] | None = None,
        on_missing_identity: Literal["deny", "anonymous"] = "deny",
        on_denied: Callable[[Request, str], Response] | None = None,
        on_error: Literal["deny", "unavailable"] = "deny",
        policies_dir: str | Path | None = None,
    ) -> None:
        self.app = app
        self.config = config
        self.exclude_paths = [re.compile(p) for p in (exclude_paths or [])]
        self.exclude_methods = set(exclude_methods or ["OPTIONS", "HEAD"])
        self.on_missing_identity = on_missing_identity
        self.on_denied = on_denied
        self.on_error = on_error

        # --- Resolution chain setup ---
        # Scan explicit policy files
        self._scanned_policies: set[str] | None = None
        if policies_dir is not None:
            self._scanned_policies = scan_policy_files(policies_dir)
            logger.info(
                "Scanned %d policy files from %s", len(self._scanned_policies), policies_dir
            )

        # Pre-compile policy group patterns (avoid per-request re.compile)
        self._compiled_groups = _compile_policy_groups(config.policy_groups)

        # Warn if multiple groups could match same common prefixes
        for i, (p1, _) in enumerate(self._compiled_groups):
            for j, (p2, _) in enumerate(self._compiled_groups):
                if i < j:
                    for test in ["/api/", "/admin/", "/api/v1/"]:
                        if p1.match(test) and p2.match(test):
                            logger.warning(
                                "PolicyGroup patterns %r and %r both match %r — first wins",
                                p1.pattern,
                                p2.pattern,
                                test,
                            )

        # Startup warnings for missing policy files
        if self._scanned_policies is not None:
            if config.default_policy and config.default_policy not in self._scanned_policies:
                logger.warning(
                    "default_policy %r not found in %s",
                    config.default_policy,
                    policies_dir,
                )
            for group in config.policy_groups:
                if group.policy_path not in self._scanned_policies:
                    logger.warning(
                        "PolicyGroup policy_path %r not found in %s",
                        group.policy_path,
                        policies_dir,
                    )

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

    def _resolve_policy(
        self,
        specific_policy_path: str,
        route_path: str,
    ) -> tuple[str, str]:
        """Run the resolution chain to determine which policy to evaluate.

        Returns:
            A ``(policy_path, resolution_source)`` tuple where
            *resolution_source* is one of ``"explicit"``, ``"group"``,
            ``"default"``, or ``"generated"``.
        """
        # 1. Explicit .rego file exists in scanned set → use it
        if self._scanned_policies is not None and specific_policy_path in self._scanned_policies:
            return specific_policy_path, "explicit"

        # 2. First matching policy group wins
        for compiled_pattern, group_policy_path in self._compiled_groups:
            if compiled_pattern.match(route_path):
                logger.debug(
                    "Route %s matched group %s -> %s",
                    route_path,
                    compiled_pattern.pattern,
                    group_policy_path,
                )
                return group_policy_path, "group"

        # 3. Fall back to default policy
        if self.config.default_policy:
            logger.debug(
                "Route %s using default_policy -> %s",
                route_path,
                self.config.default_policy,
            )
            return self.config.default_policy, "default"

        # 4. No resolution config → use auto-generated policy path
        return specific_policy_path, "generated"

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
            audit_logger = self.config.audit_logger
            if audit_logger is not None and audit_logger.log_skipped:
                await audit_logger.log_skipped_event(Request(scope, receive), "excluded")
            await self.app(scope, receive, send)
            return

        # No matched route - pass through (will be 404)
        if route is None:
            await self.app(scope, receive, send)
            return

        # Generate policy path and resolve through chain
        route_path = getattr(route, "path", path)
        policy_path = _resolve_policy_path(
            self.config.policy_path_root,
            method,
            route_path,
            self.config.policy_path_normalizer,
        )
        policy_path, resolution_source = self._resolve_policy(policy_path, route_path)

        # Inject path_params into scope so Request.path_params works
        # in identity_provider and resource_context_provider
        scope["path_params"] = path_params

        # Create request for identity extraction
        request = Request(scope, receive)

        # Extract identity
        try:
            identity = self.config.identity_provider(request)
        except Exception:
            logger.exception("identity_provider raised for %s %s", method, path)
            identity = None

        # Handle missing identity
        if identity is None or not identity.value:
            if self.on_missing_identity == "deny":
                if self.config.audit_logger:
                    await self.config.audit_logger.log_unauthenticated_event(
                        request, "missing_identity"
                    )
                response = JSONResponse(status_code=401, content={"detail": "Unauthorized"})
                await response(scope, receive, send)
                return
            identity = Identity(type=IdentityType.IDENTITY_TYPE_NONE, value="anonymous")

        # Build resource context
        resource_context = {}
        if self.config.resource_context_provider:
            resource_context.update(self.config.resource_context_provider(request))
        resource_context.update(path_params)

        # Check authorization; audit events are emitted by check_decision
        check_error: Exception | None = None
        try:
            allowed = await self.config.check_decision(
                request,
                policy_path,
                "allowed",
                resource_context or None,
                source="middleware",
                policy_resolution_source=resolution_source,
            )
        except Exception as e:
            logger.exception("Authorization check failed in middleware for policy %s", policy_path)
            check_error = e
            allowed = False

        if check_error is not None:
            if self.on_error == "unavailable":
                response = JSONResponse(
                    status_code=503,
                    content={"detail": "Authorization service unavailable"},
                )
            elif self.on_denied:
                response = self.on_denied(request, policy_path)
            else:
                response = JSONResponse(status_code=403, content={"detail": "Forbidden"})
            await response(scope, receive, send)
            return

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

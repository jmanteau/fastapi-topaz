"""TopazConfig and supporting types for Topaz authorization."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

from aserto.client import AuthorizerOptions, Identity, ResourceContext
from aserto.client.authorizer.aio import AuthorizerClient
from fastapi import Request

from ._client import SharedAuthorizerClient
from ._policy import _resolve_policy_path

if TYPE_CHECKING:
    from .audit import AuditLogger
    from .cache import DecisionCache
    from .circuit_breaker import CircuitBreaker
    from .connection_pool import ConnectionPool
    from .observability import OTelTracing, PrometheusMetrics

logger = logging.getLogger("fastapi_topaz")


def _resolve_id_source(id_source: str | Callable[[Request], str], request: Request) -> str:
    """
    Resolve an ID source to an actual value.

    Args:
        id_source: ID source specification or callable
        request: The FastAPI request object

    ID source formats:
        - "param_name" -> request.path_params["param_name"]
        - "header:X-Name" -> request.headers["X-Name"]
        - "query:name" -> request.query_params["name"]
        - "static:value" -> literal "value"
        - callable -> callable(request)

    Returns:
        The resolved ID string

    Raises:
        ValueError: If the resolved value is empty (missing path param, header,
            query param, or a callable returning an empty string). An empty
            object ID would silently be checked against ``object_id=""`` in
            Topaz, which is a misconfiguration, never a valid check.
    """
    if callable(id_source):
        resolved = id_source(request)
        if not resolved:
            raise ValueError(
                "id_source callable returned an empty object ID "
                f"for {request.method} {request.url.path}"
            )
        return resolved

    if id_source.startswith("header:"):
        header_name = id_source[7:]
        resolved = request.headers.get(header_name, "")
        if not resolved:
            raise ValueError(
                f"id_source header {header_name!r} is missing or empty "
                f"on {request.method} {request.url.path}"
            )
        return resolved

    if id_source.startswith("query:"):
        query_name = id_source[6:]
        resolved = request.query_params.get(query_name, "")
        if not resolved:
            raise ValueError(
                f"id_source query parameter {query_name!r} is missing or empty "
                f"on {request.method} {request.url.path}"
            )
        return resolved

    if id_source.startswith("static:"):
        return id_source[7:]

    # Default: path parameter
    resolved = str(request.path_params.get(id_source, ""))
    if not resolved:
        available = sorted(request.path_params.keys())
        raise ValueError(
            f"id_source path parameter {id_source!r} is missing or empty "
            f"on {request.method} {request.url.path}; available path params: {available}"
        )
    return resolved


@dataclass
class HierarchyResult:
    """Result of a hierarchy authorization check.

    Attributes:
        allowed: Whether the hierarchy check passed
        checks: List of (object_type, object_id, relation, result) tuples
        denied_at: Object type where access was denied (mode="all")
        first_match: Relation that matched first (mode="first_match")
    """

    allowed: bool
    checks: list[tuple[str, str, str, bool]]
    denied_at: str | None = None
    first_match: str | None = None

    def as_dict(self) -> dict[str, bool]:
        """Return dict mapping object_type to boolean result."""
        return {obj_type: result for obj_type, _, _, result in self.checks}


@dataclass(frozen=True)
class PolicyGroup:
    """Route pattern mapped to a shared Topaz policy.

    Allows multiple routes matching a URL pattern to share a single policy
    instead of requiring individual ``.rego`` files for each route.

    Args:
        url_pattern: Regex matched against the route *template*
            (e.g. ``/api/v1/admin/{job_id}``), **not** the concrete URL.
            Use ``^`` anchors for predictable matching.
        policy_path: Fully-qualified Topaz policy path to evaluate
            (e.g. ``"myapp.defaults.platform_admin"``).

    Example::

        PolicyGroup(
            url_pattern=r"^/api/v\\d+/(admin|internal)/",
            policy_path="myapp.defaults.platform_admin",
        )
    """

    url_pattern: str
    policy_path: str


class TopazConfig:
    """
    Configuration for Topaz authorization.
    Create once at app startup, use to generate authorization dependencies.

    Args:
        authorizer_options: Connection settings for Topaz authorizer
        policy_path_root: Root package name for policies (e.g., "myapp")
        identity_provider: Function to extract user identity from request
        policy_instance_name: Name of policy instance to evaluate
        policy_instance_label: Label for policy instance (defaults to name)
        resource_context_provider: Function to provide additional context
        policy_path_normalizer: Optional callable to transform generated policy
            paths (e.g., replace hyphens with underscores for valid Rego identifiers)
        default_policy: Optional fallback policy path evaluated when no explicit
            policy file exists and no policy group matches. All requests still go
            through Topaz — this only changes *which* policy is evaluated.
        policy_groups: Optional ordered list of :class:`PolicyGroup` entries.
            The first group whose ``url_pattern`` matches the route template wins.
        decision_cache: Optional cache for authorization decisions
        max_concurrent_checks: Max concurrent authorization checks for bulk operations (default: 10)
        check_timeout: gRPC deadline in seconds applied to each authorization
            call (default: 5.0). Set to None to disable the deadline.
        circuit_breaker: Optional circuit breaker for graceful degradation
        connection_pool: Deprecated, has no effect on authorization calls
            (authorization checks use a single shared gRPC channel)
        audit_logger: Optional audit logger for authorization decisions
        metrics: Optional Prometheus metrics collector
        tracing: Optional OpenTelemetry tracing
    """

    def __init__(
        self,
        *,
        authorizer_options: AuthorizerOptions,
        policy_path_root: str,
        identity_provider: Callable[[Request], Identity],
        policy_instance_name: str,
        policy_instance_label: str | None = None,
        resource_context_provider: Callable[[Request], ResourceContext] | None = None,
        policy_path_normalizer: Callable[[str], str] | None = None,
        default_policy: str | None = None,
        policy_groups: list[PolicyGroup] | None = None,
        decision_cache: DecisionCache | None = None,
        max_concurrent_checks: int = 10,
        check_timeout: float | None = 5.0,
        circuit_breaker: CircuitBreaker | None = None,
        connection_pool: ConnectionPool | None = None,
        audit_logger: AuditLogger | None = None,
        metrics: PrometheusMetrics | None = None,
        tracing: OTelTracing | None = None,
    ):
        self.authorizer_options = authorizer_options
        self.policy_path_root = policy_path_root
        self.identity_provider = identity_provider
        self.policy_instance_name = policy_instance_name
        self.policy_instance_label = policy_instance_label or policy_instance_name
        self.resource_context_provider = resource_context_provider
        self.policy_path_normalizer = policy_path_normalizer
        self.default_policy = default_policy
        self.policy_groups = tuple(policy_groups or [])
        self.decision_cache = decision_cache
        self.max_concurrent_checks = max_concurrent_checks
        self.check_timeout = check_timeout
        self.circuit_breaker = circuit_breaker
        self.connection_pool = connection_pool
        self.audit_logger = audit_logger
        self.metrics = metrics
        self.tracing = tracing
        self._authorizer = SharedAuthorizerClient(authorizer_options)
        # asyncio primitives are created lazily on first use: on Python 3.9
        # they bind the event loop active at creation time, and configs are
        # typically created at module import, outside any loop
        self._semaphore: asyncio.Semaphore | None = None
        # Stale cache for circuit breaker fallback (stores entries beyond normal TTL)
        self._stale_cache: dict[str, tuple[bool, float]] = {}
        self._stale_cache_lock: asyncio.Lock | None = None

        # Validate policy_groups regex patterns at config creation time
        if self.policy_groups:
            from ._policy import _compile_policy_groups

            _compile_policy_groups(self.policy_groups)  # raises ValueError on bad regex

        # Guard against empty string default_policy
        if default_policy is not None and not default_policy:
            raise ValueError("default_policy must be a non-empty string or None")

        # Configure connection pool with authorizer options
        if self.connection_pool:
            self.connection_pool.configure(authorizer_options)

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazily create the concurrency semaphore from within a running loop.

        No lock needed: the check-and-assign is synchronous, so it cannot be
        interleaved by other tasks on the same event loop.
        """
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent_checks)
        return self._semaphore

    def _get_stale_cache_lock(self) -> asyncio.Lock:
        """Lazily create the stale-cache lock from within a running loop."""
        if self._stale_cache_lock is None:
            self._stale_cache_lock = asyncio.Lock()
        return self._stale_cache_lock

    def create_client(self, request: Request) -> AuthorizerClient:
        """Create a Topaz authorizer client with identity from request.

        .. deprecated::
            No longer used internally — authorization checks go through a
            single shared gRPC channel. Each call to this method opens a new
            channel that the caller must close. Will be removed in 2.0.
        """
        identity = self.identity_provider(request)
        return AuthorizerClient(identity=identity, options=self.authorizer_options)

    def _make_stale_cache_key(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
    ) -> str:
        """Create a key for the stale cache."""
        ctx_str = str(sorted(resource_context.items())) if resource_context else ""
        key_data = f"{identity_value}:{policy_path}:{decision}:{ctx_str}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]

    async def _get_stale_cached(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
    ) -> bool | None:
        """Get a potentially stale cached decision for circuit breaker fallback."""
        if not self.circuit_breaker or not self.circuit_breaker.serve_stale_cache:
            return None

        key = self._make_stale_cache_key(identity_value, policy_path, decision, resource_context)
        async with self._get_stale_cache_lock():
            if key not in self._stale_cache:
                return None

            value, cached_at = self._stale_cache[key]
            stale_age = time.monotonic() - cached_at

            if stale_age > self.circuit_breaker.stale_cache_ttl:
                # Too stale, remove it
                del self._stale_cache[key]
                return None

            return value

    async def _set_stale_cached(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
        value: bool,
    ) -> None:
        """Store a decision in the stale cache for circuit breaker fallback."""
        if not self.circuit_breaker:
            return

        key = self._make_stale_cache_key(identity_value, policy_path, decision, resource_context)
        async with self._get_stale_cache_lock():
            self._stale_cache[key] = (value, time.monotonic())

            # Simple size limit - remove oldest entries if too large
            max_stale_cache = 10000
            if len(self._stale_cache) > max_stale_cache:
                # Remove 10% of oldest entries
                sorted_keys = sorted(
                    self._stale_cache.keys(), key=lambda k: self._stale_cache[k][1]
                )
                for k in sorted_keys[: max_stale_cache // 10]:
                    del self._stale_cache[k]

    async def check_decision(
        self,
        request: Request,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None = None,
        source: str = "dependency",
        policy_resolution_source: str | None = None,
    ) -> bool:
        """
        Check an authorization decision, using cache if available.

        This is the core authorization check method that handles caching,
        circuit breaker logic, and can be used directly for custom authorization logic.

        When ``audit_logger`` is configured, every call emits exactly one audit
        event, regardless of caller (middleware, dependency, or manual API).
        """
        identity = self.identity_provider(request)
        start_time = time.monotonic()
        cached_result = False
        result: bool = False
        span = None
        check_error: Exception | None = None

        # Start tracing span
        if self.tracing:
            span = self.tracing.start_auth_span(
                source=source,
                check_type="policy",
                policy_path=policy_path,
                identity_value=identity.value if identity else None,
            )

        try:
            # Check fresh cache first
            identity_value = identity.value or ""
            if self.decision_cache:
                cached = await self.decision_cache.get(
                    identity_value, policy_path, decision, resource_context
                )
                if cached is not None:
                    logger.debug(f"Cache HIT: {policy_path}, decision={decision}")
                    cached_result = True
                    if self.metrics:
                        self.metrics.record_cache_hit(source)
                    result = cached
                    return result
                else:
                    if self.metrics:
                        self.metrics.record_cache_miss(source)

            # Check circuit breaker - should we attempt the call?
            if self.circuit_breaker:
                should_call = await self.circuit_breaker.should_allow_request()
                if not should_call:
                    # Circuit is open, use fallback
                    stale_cached = await self._get_stale_cached(
                        identity_value, policy_path, decision, resource_context
                    )
                    logger.warning(
                        f"Circuit OPEN, using fallback for {policy_path} "
                        f"(stale_cache={'hit' if stale_cached is not None else 'miss'})"
                    )

                    result = await self.circuit_breaker.get_fallback_decision(
                        request,
                        policy_path,
                        dict(resource_context) if resource_context else {},
                        stale_cached,
                        ConnectionError("Circuit breaker open"),
                    )

                    if self.metrics:
                        self.metrics.record_fallback(
                            "circuit_open",
                            stale_cached is not None,
                            "allowed" if result else "denied",
                        )

                    if self.circuit_breaker.on_fallback:
                        try:
                            self.circuit_breaker.on_fallback(
                                request, policy_path, stale_cached, result
                            )
                        except Exception as e:
                            logger.error(f"Error in on_fallback callback: {e}")

                    return result

            # Make the authorization call over the shared channel
            topaz_start = time.monotonic()
            decisions_result = await self._authorizer.decisions(
                identity=identity,
                policy_path=policy_path,
                decisions=(decision,),
                policy_instance_name=self.policy_instance_name,
                policy_instance_label=self.policy_instance_label,
                resource_context=resource_context,
                timeout=self.check_timeout,
            )
            result = decisions_result.get(decision, False)
            topaz_latency = time.monotonic() - topaz_start

            if self.metrics:
                self.metrics.record_topaz_latency(topaz_latency)

            # Record success with circuit breaker
            if self.circuit_breaker:
                await self.circuit_breaker.record_success()

            # Cache the result
            if self.decision_cache:
                await self.decision_cache.set(
                    identity_value, policy_path, decision, resource_context, result
                )

            # Store in stale cache for circuit breaker fallback
            await self._set_stale_cached(
                identity_value, policy_path, decision, resource_context, result
            )

            return result

        except Exception as e:
            check_error = e
            if self.metrics:
                self.metrics.record_error(type(e).__name__)
            if self.tracing and span:
                self.tracing.record_error(span, e)
                span = None  # Don't end span twice

            # Check if this is a failure that should trip the circuit breaker
            if self.circuit_breaker and self.circuit_breaker.is_failure_exception(e):
                await self.circuit_breaker.record_failure(e)

                # Try fallback
                stale_cached = await self._get_stale_cached(
                    identity_value, policy_path, decision, resource_context
                )
                logger.warning(
                    f"Topaz call failed ({type(e).__name__}), using fallback for {policy_path}"
                )

                result = await self.circuit_breaker.get_fallback_decision(
                    request,
                    policy_path,
                    dict(resource_context) if resource_context else {},
                    stale_cached,
                    e,
                )

                if self.metrics:
                    self.metrics.record_fallback(
                        "error",
                        stale_cached is not None,
                        "allowed" if result else "denied",
                    )

                if self.circuit_breaker.on_fallback:
                    try:
                        self.circuit_breaker.on_fallback(request, policy_path, stale_cached, result)
                    except Exception as cb_error:
                        logger.error(f"Error in on_fallback callback: {cb_error}")

                # Fallback produced a decision — not a propagating error
                check_error = None
                return result

            # Not a circuit breaker failure, re-raise
            raise

        finally:
            latency_seconds = time.monotonic() - start_time
            latency_ms = latency_seconds * 1000
            result_decision = "allowed" if result else "denied"

            # Record metrics
            if self.metrics:
                self.metrics.record_auth_request(
                    source=source,
                    decision=result_decision,
                    check_type="policy",
                    policy_path=policy_path,
                )
                self.metrics.record_latency(latency_seconds, source, cached_result, policy_path)

            # End tracing span
            if self.tracing and span:
                self.tracing.end_auth_span(
                    span,
                    decision=result_decision,
                    cached=cached_result,
                    latency_ms=latency_ms,
                    resource_context=dict(resource_context) if resource_context else None,
                )

            # Audit logging — single emission point for all sources
            if self.audit_logger:
                ctx = dict(resource_context) if resource_context else None
                is_rebac = bool(ctx and ctx.get("object_type") and ctx.get("relation"))

                def _ctx_str(key: str) -> str | None:
                    if not is_rebac or not ctx:
                        return None
                    value = ctx.get(key)
                    return str(value) if value is not None else None

                await self.audit_logger.log_decision(
                    request=request,
                    policy_path=policy_path,
                    allowed=result,
                    source=source,
                    check_type="rebac" if is_rebac else "policy",
                    cached=cached_result,
                    latency_ms=latency_ms,
                    identity_type=identity.type.name  # type: ignore[union-attr]
                    if hasattr(identity.type, "name")
                    else str(identity.type),
                    identity_value=identity.value,
                    object_type=_ctx_str("object_type"),
                    object_id=_ctx_str("object_id"),
                    relation=_ctx_str("relation"),
                    subject_type=_ctx_str("subject_type"),
                    resource_context=ctx,
                    policy_resolution_source=policy_resolution_source,
                    reason="authorizer_error" if check_error is not None else None,
                )

    def policy_path_for(self, method: str, route_path: str) -> str:
        """
        Generate the policy path for a given HTTP method and route path.

        Useful for debugging, testing, or previewing what policy path
        will be generated for a given route.

        Args:
            method: HTTP method (e.g., "GET", "POST")
            route_path: URL path pattern (e.g., "/documents/{id}")

        Returns:
            The policy path that would be used for authorization

        Example:
            >>> config.policy_path_for("GET", "/documents/{id}")
            "myapp.GET.documents.__id"
        """
        return _resolve_policy_path(
            self.policy_path_root, method, route_path, self.policy_path_normalizer
        )

    async def is_allowed(
        self,
        request: Request,
        policy_path: str,
        resource_context: ResourceContext | None = None,
        decision: str = "allowed",
        source: str = "manual",
    ) -> bool:
        """
        Check if an action is allowed without raising an exception.

        This is a non-raising alternative to require_policy_allowed that returns
        True/False instead of raising HTTPException(403). Useful for UI patterns
        where you need to check permissions without blocking (e.g., showing/hiding
        edit or delete buttons).

        Args:
            request: The FastAPI request object
            policy_path: Full policy path (e.g., "webapp.PUT.documents")
            resource_context: Optional resource context dict
            decision: Decision to check (default: "allowed")

        Returns:
            True if allowed, False otherwise

        Example:
            ```python
            @app.get("/documents/{id}")
            async def get_document(id: int, request: Request):
                doc = await fetch_document(id)
                can_edit = await config.is_allowed(
                    request,
                    policy_path="myapp.PUT.documents",
                    resource_context={"id": str(id)},
                )
                return {"document": doc, "can_edit": can_edit}
            ```
        """
        ctx: ResourceContext = dict(resource_context) if resource_context else {}
        if self.resource_context_provider:
            ctx.update(self.resource_context_provider(request))
        if request.path_params:
            ctx.update(request.path_params)

        return await self.check_decision(request, policy_path, decision, ctx, source=source)

    async def check_relation(
        self,
        request: Request,
        object_type: str,
        object_id: str,
        relation: str,
        subject_type: str = "user",
        source: str = "manual",
    ) -> bool:
        """
        Check a ReBAC relation without raising an exception.

        This is a non-raising alternative to require_rebac_allowed that returns
        True/False instead of raising HTTPException(403). Useful for checking
        if a user has a specific relationship with an object.

        Args:
            request: The FastAPI request object
            object_type: Type of object (e.g., "document", "folder")
            object_id: ID of the object to check
            relation: Relation to check (e.g., "can_read", "can_write", "can_delete")
            subject_type: Subject type (default: "user")

        Returns:
            True if the relation exists, False otherwise

        Example:
            ```python
            @app.get("/documents/{id}")
            async def get_document(id: int, request: Request):
                doc = await fetch_document(id)
                can_delete = await config.check_relation(
                    request,
                    object_type="document",
                    object_id=str(id),
                    relation="can_delete",
                )
                return {"document": doc, "can_delete": can_delete}
            ```
        """
        resource_ctx: ResourceContext = {}
        if self.resource_context_provider:
            resource_ctx.update(self.resource_context_provider(request))

        resource_ctx.update(
            {
                "object_type": object_type,
                "object_id": object_id,
                "relation": relation,
                "subject_type": subject_type,
            }
        )

        policy_path = f"{self.policy_path_root}.check"
        return await self.check_decision(
            request, policy_path, "allowed", resource_ctx, source=source
        )

    async def check_relations(
        self,
        request: Request,
        object_type: str,
        object_id: str,
        relations: list[str],
        subject_type: str = "user",
        source: str = "manual",
    ) -> dict[str, bool]:
        """
        Check multiple ReBAC relations at once without raising exceptions.

        This method checks multiple relations concurrently and returns a dict
        mapping relation names to boolean results. Useful for fetching all
        permissions for an object in a single call (e.g., to populate a
        permissions object in an API response).

        Args:
            request: The FastAPI request object
            object_type: Type of object (e.g., "document", "folder")
            object_id: ID of the object to check
            relations: List of relations to check (e.g., ["can_read", "can_write", "can_delete"])
            subject_type: Subject type (default: "user")

        Returns:
            Dict mapping relation names to boolean results

        Example:
            ```python
            @app.get("/documents/{id}")
            async def get_document(id: int, request: Request):
                doc = await fetch_document(id)
                permissions = await config.check_relations(
                    request,
                    object_type="document",
                    object_id=str(id),
                    relations=["can_read", "can_write", "can_delete", "can_share"],
                )
                # permissions = {"can_read": True, "can_write": True, "can_delete": False, "can_share": False}
                return {"document": doc, "permissions": permissions}
            ```
        """

        async def check_single_relation(rel: str) -> tuple[str, bool]:
            async with self._get_semaphore():
                result = await self.check_relation(
                    request,
                    object_type=object_type,
                    object_id=object_id,
                    relation=rel,
                    subject_type=subject_type,
                    source=source,
                )
            return rel, result

        results = await asyncio.gather(*[check_single_relation(rel) for rel in relations])
        return dict(results)

    async def check_hierarchy(
        self,
        request: Request,
        checks: list[tuple[str, str, str]],
        mode: Literal["all", "any", "first_match"] = "all",
        subject_type: str = "user",
        optimize: bool = True,
        source: str = "manual",
    ) -> HierarchyResult:
        """
        Check multiple ReBAC relations for hierarchical resources.

        This is a non-raising method that returns a HierarchyResult instead of
        raising HTTPException. Use this for UI patterns where you need to check
        a hierarchy of permissions without blocking.

        Args:
            request: The FastAPI request object
            checks: List of (object_type, id_source, relation) tuples
            mode: Check mode - "all" (AND), "any" (OR), or "first_match"
            subject_type: Subject type (default: "user")
            optimize: Run checks concurrently when possible (default: True)

        Returns:
            HierarchyResult with check results and metadata

        Example:
            ```python
            @app.get("/orgs/{org_id}/projects/{proj_id}/docs/{doc_id}")
            async def get_doc(request: Request, org_id: str, proj_id: str, doc_id: str):
                result = await config.check_hierarchy(
                    request,
                    checks=[
                        ("organization", "org_id", "member"),
                        ("project", "proj_id", "viewer"),
                        ("document", "doc_id", "can_read"),
                    ],
                )
                return {"allowed": result.allowed, "access_chain": result.as_dict()}
            ```
        """
        # For first_match, order matters - run sequentially
        if mode == "first_match" or not optimize:
            return await self._check_hierarchy_sequential(
                request, checks, mode, subject_type, source
            )

        # For "all" and "any" modes with optimize=True, run concurrently
        return await self._check_hierarchy_concurrent(request, checks, mode, subject_type, source)

    async def _check_hierarchy_sequential(
        self,
        request: Request,
        checks: list[tuple[str, str, str]],
        mode: Literal["all", "any", "first_match"],
        subject_type: str,
        source: str = "manual",
    ) -> HierarchyResult:
        """Sequential check with short-circuit based on mode."""
        results: list[tuple[str, str, str, bool]] = []

        for object_type, id_source, relation in checks:
            object_id = _resolve_id_source(id_source, request)
            allowed = await self.check_relation(
                request, object_type, object_id, relation, subject_type, source=source
            )
            results.append((object_type, object_id, relation, allowed))

            # Short-circuit based on mode
            if mode == "all" and not allowed:
                return HierarchyResult(allowed=False, checks=results, denied_at=object_type)
            elif mode == "any" and allowed:
                return HierarchyResult(allowed=True, checks=results)
            elif mode == "first_match" and allowed:
                return HierarchyResult(allowed=True, checks=results, first_match=relation)

        # Final result
        if mode == "all":
            return HierarchyResult(allowed=True, checks=results)
        else:  # "any" or "first_match" with no matches
            return HierarchyResult(allowed=False, checks=results)

    async def _check_hierarchy_concurrent(
        self,
        request: Request,
        checks: list[tuple[str, str, str]],
        mode: Literal["all", "any"],
        subject_type: str,
        source: str = "manual",
    ) -> HierarchyResult:
        """Concurrent check for all/any modes."""

        async def check_one(
            check: tuple[str, str, str],
        ) -> tuple[str, str, str, bool]:
            object_type, id_source, relation = check
            object_id = _resolve_id_source(id_source, request)
            async with self._get_semaphore():
                allowed = await self.check_relation(
                    request, object_type, object_id, relation, subject_type, source=source
                )
            return object_type, object_id, relation, allowed

        results = await asyncio.gather(*[check_one(c) for c in checks])
        results_list = list(results)

        if mode == "all":
            # Find first denied
            for obj_type, _obj_id, _rel, allowed in results_list:
                if not allowed:
                    return HierarchyResult(allowed=False, checks=results_list, denied_at=obj_type)
            return HierarchyResult(allowed=True, checks=results_list)
        else:  # mode == "any"
            # Find any allowed
            any_allowed = any(allowed for _, _, _, allowed in results_list)
            return HierarchyResult(allowed=any_allowed, checks=results_list)

    async def close(self) -> None:
        """Shut down TopazConfig and release resources."""
        await self._authorizer.close()
        if self.connection_pool:
            await self.connection_pool.close()
        if self.decision_cache:
            await self.decision_cache.clear()

    async def __aenter__(self) -> TopazConfig:
        """Enter async context manager."""
        return self

    async def __aexit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any
    ) -> None:
        """Exit async context manager, closing resources."""
        await self.close()

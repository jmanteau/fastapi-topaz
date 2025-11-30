from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal, TypeVar

from aserto.client import AuthorizerOptions, Identity, ResourceContext
from aserto.client.authorizer.aio import AuthorizerClient
from fastapi import HTTPException, Request, status

if TYPE_CHECKING:
    from .audit import AuditLogger
    from .circuit_breaker import CircuitBreaker
    from .connection_pool import ConnectionPool
    from .observability import OTelTracing, PrometheusMetrics

T = TypeVar("T")
logger = logging.getLogger("fastapi_topaz")


def _policy_path_heuristic(path: str) -> str:
    """
    Convert a URL path to a policy path segment.

    Examples:
        "/" -> ""
        "/documents" -> ".documents"
        "/documents/{id}" -> ".documents.__id"
        "/users/{user_id}/docs/{doc_id}" -> ".users.__user_id.docs.__doc_id"
    """
    if not path or path == "/":
        return ""

    # Remove leading slash and split into segments
    segments = path.strip("/").split("/")
    result_parts: list[str] = []

    for segment in segments:
        if not segment:
            continue
        # Check if it's a path parameter (e.g., {id} or {user_id})
        if segment.startswith("{") and segment.endswith("}"):
            # Convert {param} to __param
            param_name = segment[1:-1]
            result_parts.append(f"__{param_name}")
        else:
            result_parts.append(segment)

    if not result_parts:
        return ""

    return "." + ".".join(result_parts)


def _resolve_policy_path(root: str, method: str, path: str) -> str:
    """
    Build a full policy path from root, HTTP method, and URL path.

    Args:
        root: Policy path root (e.g., "myapp")
        method: HTTP method (e.g., "GET", "POST")
        path: URL path pattern (e.g., "/documents/{id}")

    Returns:
        Full policy path (e.g., "myapp.GET.documents.__id")
    """
    heuristic = _policy_path_heuristic(path)
    return f"{root}.{method}{heuristic}"


def _resolve_id_source(
    id_source: str | Callable[[Request], str], request: Request
) -> str:
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
    """
    if callable(id_source):
        return id_source(request)

    if id_source.startswith("header:"):
        header_name = id_source[7:]
        return request.headers.get(header_name, "")

    if id_source.startswith("query:"):
        query_name = id_source[6:]
        return request.query_params.get(query_name, "")

    if id_source.startswith("static:"):
        return id_source[7:]

    # Default: path parameter
    return str(request.path_params.get(id_source, ""))


@dataclass
class CacheEntry:
    """A cached authorization decision with expiration."""

    value: bool
    expires_at: float


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


@dataclass
class DecisionCache:
    """
    Simple in-memory TTL cache for authorization decisions.

    Args:
        ttl_seconds: Time-to-live for cache entries (default: 60 seconds)
        max_size: Maximum number of entries to cache (default: 1000)
    """

    ttl_seconds: float = 60.0
    max_size: int = 1000
    _cache: dict[str, CacheEntry] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _make_key(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
    ) -> str:
        """Create a cache key from authorization parameters."""
        ctx_str = str(sorted(resource_context.items())) if resource_context else ""
        key_data = f"{identity_value}:{policy_path}:{decision}:{ctx_str}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]

    async def get(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
    ) -> bool | None:
        """Get a cached decision, or None if not cached or expired."""
        key = self._make_key(identity_value, policy_path, decision, resource_context)
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._cache[key]
                return None
            return entry.value

    async def set(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
        value: bool,
    ) -> None:
        """Cache a decision."""
        key = self._make_key(identity_value, policy_path, decision, resource_context)
        async with self._lock:
            # Evict oldest entries if cache is full
            if len(self._cache) >= self.max_size:
                # Remove expired entries first
                now = time.monotonic()
                expired = [k for k, v in self._cache.items() if v.expires_at < now]
                for k in expired:
                    del self._cache[k]
                # If still full, remove oldest 10%
                if len(self._cache) >= self.max_size:
                    to_remove = list(self._cache.keys())[: self.max_size // 10]
                    for k in to_remove:
                        del self._cache[k]

            self._cache[key] = CacheEntry(
                value=value,
                expires_at=time.monotonic() + self.ttl_seconds,
            )

    async def clear(self) -> None:
        """Clear all cached entries."""
        async with self._lock:
            self._cache.clear()


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
        decision_cache: Optional cache for authorization decisions
        max_concurrent_checks: Max concurrent authorization checks for bulk operations (default: 10)
        circuit_breaker: Optional circuit breaker for graceful degradation
        connection_pool: Optional connection pool for gRPC connection reuse
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
        decision_cache: DecisionCache | None = None,
        max_concurrent_checks: int = 10,
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
        self.decision_cache = decision_cache
        self.max_concurrent_checks = max_concurrent_checks
        self.circuit_breaker = circuit_breaker
        self.connection_pool = connection_pool
        self.audit_logger = audit_logger
        self.metrics = metrics
        self.tracing = tracing
        self._semaphore: asyncio.Semaphore | None = None
        # Stale cache for circuit breaker fallback (stores entries beyond normal TTL)
        self._stale_cache: dict[str, tuple[bool, float]] = {}

        # Configure connection pool with authorizer options
        if self.connection_pool:
            self.connection_pool.configure(authorizer_options)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Lazy-initialized semaphore for concurrent check limiting."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent_checks)
        return self._semaphore

    def create_client(self, request: Request) -> AuthorizerClient:
        """Create a Topaz authorizer client with identity from request."""
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
        import hashlib

        ctx_str = str(sorted(resource_context.items())) if resource_context else ""
        key_data = f"{identity_value}:{policy_path}:{decision}:{ctx_str}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]

    def _get_stale_cached(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
    ) -> bool | None:
        """Get a potentially stale cached decision for circuit breaker fallback."""
        if not self.circuit_breaker or not self.circuit_breaker.serve_stale_cache:
            return None

        key = self._make_stale_cache_key(
            identity_value, policy_path, decision, resource_context
        )
        if key not in self._stale_cache:
            return None

        value, cached_at = self._stale_cache[key]
        stale_age = time.monotonic() - cached_at

        if stale_age > self.circuit_breaker.stale_cache_ttl:
            # Too stale, remove it
            del self._stale_cache[key]
            return None

        return value

    def _set_stale_cached(
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

        key = self._make_stale_cache_key(
            identity_value, policy_path, decision, resource_context
        )
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
    ) -> bool:
        """
        Check an authorization decision, using cache if available.

        This is the core authorization check method that handles caching,
        circuit breaker logic, and can be used directly for custom authorization logic.
        """
        identity = self.identity_provider(request)
        start_time = time.monotonic()
        cached_result = False
        span = None

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
                    return cached
                else:
                    if self.metrics:
                        self.metrics.record_cache_miss(source)

            # Check circuit breaker - should we attempt the call?
            if self.circuit_breaker:
                should_call = await self.circuit_breaker.should_allow_request()
                if not should_call:
                    # Circuit is open, use fallback
                    stale_cached = self._get_stale_cached(
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

            # Make the authorization call
            topaz_start = time.monotonic()
            client = self.create_client(request)
            decisions_result = await client.decisions(
                policy_path=policy_path,
                decisions=(decision,),
                policy_instance_name=self.policy_instance_name,
                policy_instance_label=self.policy_instance_label,
                resource_context=resource_context,
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
            self._set_stale_cached(
                identity_value, policy_path, decision, resource_context, result
            )

            return result

        except Exception as e:
            if self.metrics:
                self.metrics.record_error(type(e).__name__)
            if self.tracing and span:
                self.tracing.record_error(span, e)
                span = None  # Don't end span twice

            # Check if this is a failure that should trip the circuit breaker
            if self.circuit_breaker and self.circuit_breaker.is_failure_exception(e):
                await self.circuit_breaker.record_failure(e)

                # Try fallback
                stale_cached = self._get_stale_cached(
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
                        self.circuit_breaker.on_fallback(
                            request, policy_path, stale_cached, result
                        )
                    except Exception as cb_error:
                        logger.error(f"Error in on_fallback callback: {cb_error}")

                return result

            # Not a circuit breaker failure, re-raise
            raise

        finally:
            latency_seconds = time.monotonic() - start_time
            latency_ms = latency_seconds * 1000
            result_decision = "allowed" if locals().get("result", False) else "denied"

            # Record metrics
            if self.metrics:
                self.metrics.record_auth_request(
                    source=source,
                    decision=result_decision,
                    check_type="policy",
                    policy_path=policy_path,
                )
                self.metrics.record_latency(
                    latency_seconds, source, cached_result, policy_path
                )

            # End tracing span
            if self.tracing and span:
                self.tracing.end_auth_span(
                    span,
                    decision=result_decision,
                    cached=cached_result,
                    latency_ms=latency_ms,
                    resource_context=dict(resource_context) if resource_context else None,
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
        return _resolve_policy_path(self.policy_path_root, method, route_path)

    async def is_allowed(
        self,
        request: Request,
        policy_path: str,
        resource_context: ResourceContext | None = None,
        decision: str = "allowed",
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

        return await self.check_decision(request, policy_path, decision, ctx)

    async def check_relation(
        self,
        request: Request,
        object_type: str,
        object_id: str,
        relation: str,
        subject_type: str = "user",
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

        resource_ctx.update({
            "object_type": object_type,
            "object_id": object_id,
            "relation": relation,
            "subject_type": subject_type,
        })

        policy_path = f"{self.policy_path_root}.check"
        return await self.check_decision(request, policy_path, "allowed", resource_ctx)

    async def check_relations(
        self,
        request: Request,
        object_type: str,
        object_id: str,
        relations: list[str],
        subject_type: str = "user",
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
            async with self.semaphore:
                result = await self.check_relation(
                    request,
                    object_type=object_type,
                    object_id=object_id,
                    relation=rel,
                    subject_type=subject_type,
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
                request, checks, mode, subject_type
            )

        # For "all" and "any" modes with optimize=True, run concurrently
        return await self._check_hierarchy_concurrent(
            request, checks, mode, subject_type
        )

    async def _check_hierarchy_sequential(
        self,
        request: Request,
        checks: list[tuple[str, str, str]],
        mode: Literal["all", "any", "first_match"],
        subject_type: str,
    ) -> HierarchyResult:
        """Sequential check with short-circuit based on mode."""
        results: list[tuple[str, str, str, bool]] = []

        for object_type, id_source, relation in checks:
            object_id = _resolve_id_source(id_source, request)
            allowed = await self.check_relation(
                request, object_type, object_id, relation, subject_type
            )
            results.append((object_type, object_id, relation, allowed))

            # Short-circuit based on mode
            if mode == "all" and not allowed:
                return HierarchyResult(
                    allowed=False, checks=results, denied_at=object_type
                )
            elif mode == "any" and allowed:
                return HierarchyResult(allowed=True, checks=results)
            elif mode == "first_match" and allowed:
                return HierarchyResult(
                    allowed=True, checks=results, first_match=relation
                )

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
    ) -> HierarchyResult:
        """Concurrent check for all/any modes."""

        async def check_one(
            check: tuple[str, str, str],
        ) -> tuple[str, str, str, bool]:
            object_type, id_source, relation = check
            object_id = _resolve_id_source(id_source, request)
            async with self.semaphore:
                allowed = await self.check_relation(
                    request, object_type, object_id, relation, subject_type
                )
            return object_type, object_id, relation, allowed

        results = await asyncio.gather(*[check_one(c) for c in checks])
        results_list = list(results)

        if mode == "all":
            # Find first denied
            for obj_type, obj_id, rel, allowed in results_list:
                if not allowed:
                    return HierarchyResult(
                        allowed=False, checks=results_list, denied_at=obj_type
                    )
            return HierarchyResult(allowed=True, checks=results_list)
        else:  # mode == "any"
            # Find any allowed
            any_allowed = any(allowed for _, _, _, allowed in results_list)
            return HierarchyResult(allowed=any_allowed, checks=results_list)


def require_policy_allowed(
    config: TopazConfig,
    policy_path: str,
    decision: str = "allowed",
    resource_context: ResourceContext | None = None,
) -> Callable[[Request], Awaitable[None]]:
    """
    Async dependency that raises HTTPException(403) if policy denies access.

    Args:
        config: Topaz configuration
        policy_path: Full policy path (e.g., "webapp.POST.api.documents")
        decision: Decision to check (default: "allowed")
        resource_context: Optional resource context dict

    Returns:
        Async dependency function for FastAPI

    Example:
        ```python
        @router.post("/documents")
        async def create_document(
            _: None = Depends(require_policy_allowed(topaz_config, "webapp.POST.api.documents")),
        ):
            ...
        ```
    """

    async def dependency(request: Request) -> None:
        identity = config.identity_provider(request)

        ctx: ResourceContext = dict(resource_context) if resource_context else {}
        if config.resource_context_provider:
            ctx.update(config.resource_context_provider(request))

        # Add path params to context
        if request.path_params:
            ctx.update(request.path_params)

        logger.info(
            f"Authorization check: path={policy_path}, decision={decision}, "
            f"identity_type={identity.type}, identity_value={identity.value}"
        )
        logger.debug(f"Resource context: {ctx}")

        allowed = await config.check_decision(request, policy_path, decision, ctx)

        logger.info(f"Authorization result: policy={policy_path}, allowed={allowed}")

        if not allowed:
            logger.warning(
                f"Access DENIED: path={policy_path}, identity={identity.value}, "
                f"context={ctx}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {policy_path}",
            )

        logger.info(f"Access GRANTED: path={policy_path}, identity={identity.value}")

    return dependency


def require_policy_auto(
    config: TopazConfig,
    decision: str = "allowed",
    resource_context: ResourceContext | None = None,
) -> Callable[[Request], Awaitable[None]]:
    """
    Async dependency that auto-generates policy path from route and raises HTTPException(403) if denied.

    The policy path is automatically derived from the HTTP method and route path pattern:
    - GET /documents -> {root}.GET.documents
    - POST /documents -> {root}.POST.documents
    - GET /documents/{id} -> {root}.GET.documents.__id
    - PUT /users/{user_id}/docs/{doc_id} -> {root}.PUT.users.__user_id.docs.__doc_id

    Args:
        config: Topaz configuration
        decision: Decision to check (default: "allowed")
        resource_context: Optional resource context dict

    Returns:
        Async dependency function for FastAPI

    Example:
        ```python
        @router.get("/documents/{id}")
        async def get_document(
            id: int,
            _: None = Depends(require_policy_auto(topaz_config)),
        ):
            # Policy path auto-generated as "myapp.GET.documents.__id"
            ...
        ```
    """

    async def dependency(request: Request) -> None:
        # Extract route path pattern from FastAPI's routing
        route = request.scope.get("route")
        if route is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to determine route for policy path auto-resolution",
            )

        route_path = route.path
        method = request.method

        # Generate policy path
        policy_path = _resolve_policy_path(config.policy_path_root, method, route_path)

        identity = config.identity_provider(request)

        ctx: ResourceContext = dict(resource_context) if resource_context else {}
        if config.resource_context_provider:
            ctx.update(config.resource_context_provider(request))

        # Add path params to context
        if request.path_params:
            ctx.update(request.path_params)

        logger.info(
            f"Authorization check (auto): path={policy_path}, decision={decision}, "
            f"identity_type={identity.type}, identity_value={identity.value}"
        )
        logger.debug(f"Resource context: {ctx}")

        allowed = await config.check_decision(request, policy_path, decision, ctx)

        logger.info(f"Authorization result: policy={policy_path}, allowed={allowed}")

        if not allowed:
            logger.warning(
                f"Access DENIED: path={policy_path}, identity={identity.value}, "
                f"context={ctx}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {policy_path}",
            )

        logger.info(f"Access GRANTED: path={policy_path}, identity={identity.value}")

    return dependency


def require_rebac_allowed(
    config: TopazConfig,
    object_type: str,
    relation: str,
    object_id: str | Callable[[Request], str] | None = None,
    subject_type: str = "user",
) -> Callable[[Request], Awaitable[None]]:
    """
    Async dependency that raises HTTPException(403) if ReBAC check fails.

    Args:
        config: Topaz configuration
        object_type: Type of object (e.g., "document", "folder")
        relation: Relation to check (e.g., "can_write", "can_delete")
        object_id: Static ID, callable to extract from request, or None (uses path param "id")
        subject_type: Subject type (default: "user")

    Returns:
        Async dependency function for FastAPI

    Example:
        ```python
        @router.put("/documents/{id}")
        async def update_document(
            id: int,
            _: None = Depends(require_rebac_allowed(topaz_config, "document", "can_write")),
        ):
            ...
        ```
    """

    async def dependency(request: Request) -> None:
        # Resolve object_id
        if callable(object_id):
            obj_id = object_id(request)
        elif object_id is not None:
            obj_id = object_id
        else:
            # Default: extract from path params
            obj_id = str(request.path_params.get("id", ""))

        # Start with resource context from provider (includes document data, user info, etc.)
        resource_ctx: ResourceContext = {}
        if config.resource_context_provider:
            resource_ctx.update(config.resource_context_provider(request))

        # Add ReBAC-specific fields
        resource_ctx.update({
            "object_type": object_type,
            "object_id": obj_id,
            "relation": relation,
            "subject_type": subject_type,
        })

        policy_path = f"{config.policy_path_root}.check"

        allowed = await config.check_decision(request, policy_path, "allowed", resource_ctx)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {relation} on {object_type}:{obj_id}",
            )

    return dependency


def get_authorized_resource(
    config: TopazConfig,
    resource_fetcher: Callable[[Request, Any], T | None],
    object_type: str,
    relation: str,
    object_id: str | Callable[[Request], str] | None = None,
    subject_type: str = "user",
) -> Callable[[Request], Awaitable[T]]:
    """
    Async dependency that fetches a resource and checks authorization.
    Returns resource or raises 403/404.

    Args:
        config: Topaz configuration
        resource_fetcher: Function that takes (request, db) and returns resource or None
        object_type: Type of object (e.g., "document")
        relation: Relation to check (e.g., "can_write")
        object_id: Static ID, callable, or None (uses path param "id")
        subject_type: Subject type (default: "user")

    Returns:
        Async dependency function that returns the authorized resource

    Example:
        ```python
        def fetch_document(request: Request, db: Session) -> Document | None:
            doc_id = request.path_params["id"]
            return db.query(Document).filter(Document.id == doc_id).first()

        @router.put("/documents/{id}")
        async def update_document(
            document: Document = Depends(
                get_authorized_resource(topaz_config, fetch_document, "document", "can_write")
            ),
        ):
            # document is pre-fetched and authorized
            ...
        ```
    """

    async def dependency(request: Request) -> T:
        # First fetch the resource
        resource = resource_fetcher(request, None)  # Pass None for db, handle via additional deps

        if resource is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{object_type.capitalize()} not found",
            )

        # Resolve object_id
        if callable(object_id):
            obj_id = object_id(request)
        elif object_id is not None:
            obj_id = object_id
        else:
            obj_id = str(request.path_params.get("id", ""))

        # Check authorization
        resource_ctx: ResourceContext = {
            "object_type": object_type,
            "object_id": obj_id,
            "relation": relation,
            "subject_type": subject_type,
        }

        policy_path = f"{config.policy_path_root}.check"

        allowed = await config.check_decision(request, policy_path, "allowed", resource_ctx)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {relation} on {object_type}:{obj_id}",
            )

        return resource

    return dependency


def filter_authorized_resources(
    config: TopazConfig,
    object_type: str,
    relation: str,
    id_extractor: Callable[[Any], str] = lambda obj: str(getattr(obj, "id", "")),
    subject_type: str = "user",
) -> Callable[[Request], Awaitable[Callable[[list[T]], Awaitable[list[T]]]]]:
    """
    Async dependency that returns an async filter function to remove unauthorized resources.

    Uses concurrent authorization checks (controlled by config.max_concurrent_checks)
    and caching (if config.decision_cache is set) for optimal performance.

    Args:
        config: Topaz configuration
        object_type: Type of object (e.g., "document")
        relation: Relation to check (e.g., "can_read")
        id_extractor: Function to extract ID from resource object
        subject_type: Subject type (default: "user")

    Returns:
        Async dependency that returns an async filter function

    Example:
        ```python
        @router.get("/documents")
        async def list_documents(
            filter_fn: Callable = Depends(
                filter_authorized_resources(topaz_config, "document", "can_read")
            ),
            db: Session = Depends(get_db),
        ):
            all_docs = db.query(Document).all()
            authorized_docs = await filter_fn(all_docs)
            return authorized_docs
        ```
    """

    async def dependency(request: Request) -> Callable[[list[T]], Awaitable[list[T]]]:
        async def check_single(resource: T) -> tuple[T, bool]:
            """Check authorization for a single resource with semaphore limiting."""
            obj_id = id_extractor(resource)

            resource_ctx: ResourceContext = {
                "object_type": object_type,
                "object_id": obj_id,
                "relation": relation,
                "subject_type": subject_type,
            }

            policy_path = f"{config.policy_path_root}.check"

            # Use semaphore to limit concurrent checks
            async with config.semaphore:
                allowed = await config.check_decision(
                    request, policy_path, "allowed", resource_ctx
                )

            return resource, allowed

        async def filter_fn(resources: list[T]) -> list[T]:
            if not resources:
                return []

            # Run all checks concurrently (limited by semaphore)
            results = await asyncio.gather(*[check_single(r) for r in resources])

            # Filter to only authorized resources
            return [resource for resource, allowed in results if allowed]

        return filter_fn

    return dependency


def require_rebac_hierarchy(
    config: TopazConfig,
    checks: list[tuple[str, str, str]],
    mode: Literal["all", "any", "first_match"] = "all",
    subject_type: str = "user",
    optimize: bool = True,
) -> Callable[[Request], Awaitable[None]]:
    """
    Async dependency for hierarchical ReBAC authorization.

    Checks multiple object/relation pairs in a single dependency, reducing
    boilerplate for nested resources like /orgs/{org}/projects/{proj}/docs/{doc}.

    Args:
        config: Topaz configuration
        checks: List of (object_type, id_source, relation) tuples.
            id_source can be:
            - "param_name" -> request.path_params["param_name"]
            - "header:X-Name" -> request.headers["X-Name"]
            - "query:name" -> request.query_params["name"]
            - "static:value" -> literal "value"
            - callable -> callable(request)
        mode: Check mode:
            - "all" (default): All checks must pass (AND). Fails fast.
            - "any": At least one check must pass (OR).
            - "first_match": Return on first success.
        subject_type: Subject type (default: "user")
        optimize: Run checks concurrently when possible (default: True)

    Returns:
        Async dependency function for FastAPI

    Raises:
        HTTPException(403): If authorization fails based on mode semantics

    Example:
        ```python
        @app.get("/orgs/{org_id}/projects/{proj_id}/docs/{doc_id}")
        async def get_doc(
            _=Depends(require_rebac_hierarchy(config, [
                ("organization", "org_id", "member"),
                ("project", "proj_id", "viewer"),
                ("document", "doc_id", "can_read"),
            ])),
        ):
            ...
        ```
    """

    async def dependency(request: Request) -> None:
        result = await config.check_hierarchy(
            request, checks, mode, subject_type, optimize
        )

        if not result.allowed:
            if result.denied_at:
                detail = f"Access denied at {result.denied_at}"
            else:
                detail = "Access denied: no matching permissions"
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail,
            )

    return dependency

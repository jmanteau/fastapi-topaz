from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from collections.abc import Awaitable
from typing import Any, Callable, Literal, TypeVar, cast

from aserto.client import ResourceContext
from fastapi import HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from ._policy import _resolve_policy_path
from .config import TopazConfig

T = TypeVar("T")
logger = logging.getLogger("fastapi_topaz")


async def _check_policy_and_raise(
    config: TopazConfig,
    request: Request,
    policy_path: str,
    decision: str,
    resource_context: ResourceContext | None,
) -> None:
    """Build context, run the policy check, raise a generic 403 on deny.

    Per-request details (identity, context, decision) are logged at DEBUG;
    the audit logger is the structured record for authorization decisions.
    """
    identity = config.identity_provider(request)

    ctx = config._policy_resource_context(request, resource_context)

    logger.debug(
        f"Authorization check: path={policy_path}, decision={decision}, "
        f"identity_type={identity.type}"
    )
    logger.debug(f"Resource context: {ctx}")

    allowed = await config.check_decision(request, policy_path, decision, ctx)

    if not allowed:
        logger.debug(
            f"Access DENIED: path={policy_path}, identity_type={identity.type}, context={ctx}"
        )
        detail: str | dict = "Forbidden"
        if config.expose_deny_reason:
            detail = {"detail": "Forbidden", "policy": policy_path, "source": "dependency"}
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )

    logger.debug(f"Access GRANTED: path={policy_path}, identity_type={identity.type}")


def _raise_rebac_denied(config: TopazConfig, relation: str, object_type: str, obj_id: str) -> None:
    """Log the denied ReBAC check at DEBUG and raise a generic 403."""
    logger.debug(f"ReBAC access DENIED: {relation} on {object_type}:{obj_id}")
    detail: str | dict = "Forbidden"
    if config.expose_deny_reason:
        detail = {
            "detail": "Forbidden",
            "policy": f"{config.policy_path_root}.check",
            "source": "rebac",
            "object_type": object_type,
            "relation": relation,
        }
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def _require_object_id(obj_id: str, request: Request, expected_param: str) -> None:
    """Raise 500 when a ReBAC dependency could not resolve a non-empty object ID.

    An empty object ID means the route params do not match what the dependency
    expects (e.g. route uses ``{doc_id}`` but the dependency reads ``id``).
    Sending ``object_id=""`` to Topaz would silently check the wrong object.
    """
    if obj_id:
        return
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    logger.error(
        "Could not resolve object ID for %s %s: expected %r, available path params: %s",
        request.method,
        route_path,
        expected_param,
        sorted(request.path_params.keys()),
    )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Authorization misconfiguration: could not resolve object ID",
    )


def _reject_empty_static_object_id(object_id: str | Callable[[Request], str] | None) -> None:
    """Raise at factory time when a static object_id is empty.

    ``object_id=""`` would check the empty object in Topaz on every request.
    """
    if isinstance(object_id, str) and not object_id:
        raise ValueError("object_id must be a non-empty string, a callable, or None")


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
        await _check_policy_and_raise(config, request, policy_path, decision, resource_context)

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
        policy_path = _resolve_policy_path(
            config.policy_path_root,
            method,
            route_path,
            config.policy_path_normalizer,
        )

        await _check_policy_and_raise(config, request, policy_path, decision, resource_context)

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
    _reject_empty_static_object_id(object_id)

    async def dependency(request: Request) -> None:
        # Resolve object_id
        if callable(object_id):
            obj_id = object_id(request)
            _require_object_id(obj_id, request, "<callable object_id>")
        elif object_id is not None:
            obj_id = object_id
        else:
            # Default: extract from path params
            obj_id = str(request.path_params.get("id", ""))
            _require_object_id(obj_id, request, "id")

        # Start with resource context from provider (includes document data, user info, etc.)
        resource_ctx: ResourceContext = {}
        if config.resource_context_provider:
            resource_ctx.update(config.resource_context_provider(request))

        # Add ReBAC-specific fields
        resource_ctx.update(
            {
                "object_type": object_type,
                "object_id": obj_id,
                "relation": relation,
                "subject_type": subject_type,
            }
        )

        policy_path = f"{config.policy_path_root}.check"

        allowed = await config.check_decision(request, policy_path, "allowed", resource_ctx)

        if not allowed:
            _raise_rebac_denied(config, relation, object_type, obj_id)

    return dependency


def get_authorized_resource(
    config: TopazConfig,
    resource_fetcher: Callable[[Request], T | None | Awaitable[T | None]],
    object_type: str,
    relation: str,
    object_id: str | Callable[[Request], str] | None = None,
    subject_type: str = "user",
) -> Callable[[Request], Awaitable[T]]:
    """
    Async dependency that checks authorization, then fetches the resource.
    Returns resource or raises 403/404.

    Authorization runs first, so a denied request gets 403 whether or not the
    resource exists (no existence oracle) and the fetcher is never called.

    Args:
        config: Topaz configuration
        resource_fetcher: Function that takes (request) and returns resource or
            None. Coroutine functions are awaited; sync functions run in a
            threadpool so blocking I/O does not stall the event loop.
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
    _reject_empty_static_object_id(object_id)
    is_async_fetcher = inspect.iscoroutinefunction(resource_fetcher)

    async def dependency(request: Request) -> T:
        # Resolve object_id
        if callable(object_id):
            obj_id = object_id(request)
            _require_object_id(obj_id, request, "<callable object_id>")
        elif object_id is not None:
            obj_id = object_id
        else:
            obj_id = str(request.path_params.get("id", ""))
            _require_object_id(obj_id, request, "id")

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
            _raise_rebac_denied(config, relation, object_type, obj_id)

        # Fetch only after authorization succeeded
        if is_async_fetcher:
            resource = await cast(Callable[[Request], Awaitable["T | None"]], resource_fetcher)(
                request
            )
        else:
            resource = await run_in_threadpool(functools.partial(resource_fetcher, request))

        if resource is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{object_type.capitalize()} not found",
            )

        return cast(T, resource)

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
            if not obj_id:
                raise ValueError(
                    f"id_extractor returned an empty object ID for resource {resource!r}; "
                    f"cannot authorize {relation} on {object_type}"
                )

            resource_ctx: ResourceContext = {
                "object_type": object_type,
                "object_id": obj_id,
                "relation": relation,
                "subject_type": subject_type,
            }

            policy_path = f"{config.policy_path_root}.check"

            # Use semaphore to limit concurrent checks
            async with config._get_semaphore():
                allowed = await config.check_decision(request, policy_path, "allowed", resource_ctx)

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
        ValueError: At factory time, if ``checks`` is empty
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
    if not checks:
        # An empty "all" would vacuously allow everything
        raise ValueError("require_rebac_hierarchy() requires at least one check")

    async def dependency(request: Request) -> None:
        try:
            result = await config.check_hierarchy(
                request, checks, mode, subject_type, optimize, source="dependency"
            )
        except ValueError as e:
            logger.error(
                "Could not resolve object ID in hierarchy check for %s %s: %s",
                request.method,
                request.url.path,
                e,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authorization misconfiguration: could not resolve object ID",
            ) from e

        if not result.allowed:
            if result.denied_at:
                logger.debug(f"Hierarchy access DENIED at {result.denied_at}")
            else:
                logger.debug("Hierarchy access DENIED: no matching permissions")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )

    return dependency

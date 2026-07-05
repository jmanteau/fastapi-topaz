from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any, Callable, Literal, TypeVar

from aserto.client import ResourceContext
from fastapi import HTTPException, Request, status

from ._policy import _resolve_policy_path
from .config import TopazConfig

T = TypeVar("T")
logger = logging.getLogger("fastapi_topaz")


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
                f"Access DENIED: path={policy_path}, identity={identity.value}, context={ctx}"
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
        policy_path = _resolve_policy_path(
            config.policy_path_root,
            method,
            route_path,
            config.policy_path_normalizer,
        )

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
                f"Access DENIED: path={policy_path}, identity={identity.value}, context={ctx}"
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
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {relation} on {object_type}:{obj_id}",
            )

    return dependency


def get_authorized_resource(
    config: TopazConfig,
    resource_fetcher: Callable[[Request], T | None],
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
        resource_fetcher: Function that takes (request) and returns resource or None
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
        resource = resource_fetcher(request)

        if resource is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{object_type.capitalize()} not found",
            )

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
        try:
            result = await config.check_hierarchy(request, checks, mode, subject_type, optimize)
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
                detail = f"Access denied at {result.denied_at}"
            else:
                detail = "Access denied: no matching permissions"
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail,
            )

    return dependency

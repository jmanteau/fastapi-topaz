from __future__ import annotations

import logging
import sys
from pathlib import Path

import httpx
from fastapi import Request
from fastapi_topaz import (
    AuditLogger,
    AuthorizerOptions,
    CircuitBreaker,
    DecisionCache,
    Identity,
    IdentityType,
    ResourceContext,
    TopazConfig,
)
from fastapi_topaz.config import PolicyGroup

logger = logging.getLogger(__name__)

from app.config import settings

# Add fastapi-topaz to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "fastapi-topaz" / "src"))


def identity_provider(request: Request) -> Identity:
    """Extract identity from request session."""
    user_data = request.session.get("user")
    if user_data is None:
        return Identity(IdentityType.IDENTITY_TYPE_NONE)

    # Use MANUAL type to pass identity without directory lookup
    return Identity(type=IdentityType.IDENTITY_TYPE_MANUAL, value=user_data["sub"])


def resource_context_provider(request: Request) -> ResourceContext:
    """Build resource context with path params and user location."""
    logger.debug(f"resource_context_provider called for {request.url.path}")
    context: ResourceContext = {}

    # Add path parameters
    if hasattr(request, "path_params") and request.path_params:
        logger.debug(f"Path params: {request.path_params}")
        context.update(request.path_params)

    # Add user info to resource context so policy can access input.resource.current_user.sub
    # Note: Can't use "user" key as it's reserved by Topaz SDK
    user_data = request.session.get("user")
    if user_data:
        context["current_user"] = {
            "sub": user_data["sub"],
            "email": user_data.get("email"),
            "name": user_data.get("name"),
        }

        try:
            # Query mock location API
            response = httpx.get(
                f"{settings.location_api_url}/location",
                params={"user_id": user_data["sub"]},
                timeout=2.0,
            )
            if response.status_code == 200:
                location_data = response.json()
                context["user_location"] = location_data
        except Exception:
            # If location API fails, continue without location data
            pass

    # Fetch document data if this is a document-related request
    if "/documents/" in request.url.path and "id" in request.path_params:
        try:
            from app.database import SessionLocal
            from app.models import Document

            doc_id = int(request.path_params["id"])
            logger.debug(f"Looking up document {doc_id}")
            db = SessionLocal()
            try:
                document = db.query(Document).filter(Document.id == doc_id).first()
                if document:
                    # Add document data to context for policy evaluation
                    context["owner_id"] = document.owner_id
                    context["is_public"] = document.is_public
                    logger.debug(
                        f"Document {doc_id}: owner_id={document.owner_id}, current_user.sub={context.get('current_user', {}).get('sub')}"
                    )

                    # Add shares data
                    shares = []
                    for share in document.shares:
                        shares.append(
                            {
                                "user_id": share.user_id,
                                "permission": share.permission,
                            }
                        )
                    context["shares"] = shares
                else:
                    logger.debug(f"Document {doc_id} NOT FOUND")
            finally:
                db.close()
        except Exception as e:
            # If document fetch fails, continue without document data
            logger.debug(f"Exception fetching document: {e}")

    # Fetch folder data if this is a folder-related request
    if "/folders/" in request.url.path and "id" in request.path_params:
        logger.debug(f"Fetching folder data for {request.url.path}")
        try:
            from app.database import SessionLocal
            from app.models import Folder

            folder_id = int(request.path_params["id"])
            db = SessionLocal()
            try:
                folder = db.query(Folder).filter(Folder.id == folder_id).first()
                if folder:
                    # Add folder data to context for policy evaluation
                    context["owner_id"] = folder.owner_id
                    logger.debug(
                        f"Folder {folder_id}: owner_id={folder.owner_id}, user_sub={context.get('current_user', {}).get('sub')}"
                    )
                else:
                    logger.debug(f"Folder {folder_id} NOT FOUND")
            finally:
                db.close()
        except Exception as e:
            # If folder fetch fails, continue without folder data
            logger.debug(f"ERROR fetching folder: {e}")

    return context


# Create Topaz configuration singleton
topaz_config = TopazConfig(
    authorizer_options=AuthorizerOptions(
        url=settings.topaz_url,
        tenant_id=settings.topaz_tenant_id,
        api_key=settings.topaz_api_key,
        cert_file_path=settings.topaz_ca_cert or None,  # CA cert for TLS verification
    ),
    policy_path_root=settings.topaz_policy_root,
    identity_provider=identity_provider,
    policy_instance_name=settings.topaz_policy_instance_name,
    policy_instance_label=settings.topaz_policy_instance_label,
    resource_context_provider=resource_context_provider,
    # Resolution chain: routes without explicit .rego files use this default
    default_policy="webapp.defaults.authenticated",
    # Policy groups: URL-pattern-based policy routing (first match wins)
    policy_groups=[
        PolicyGroup(
            url_pattern=r"^/api/shares",
            policy_path="webapp.defaults.authenticated",
        ),
    ],
    decision_cache=DecisionCache(ttl_seconds=60, max_size=1000),
    circuit_breaker=CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=30,
        fallback="cache_then_deny",
        serve_stale_cache=True,
        stale_cache_ttl=300,
    ),
    audit_logger=AuditLogger(),
)

# Policies directory for explicit policy scanning (hierarchical structure)
POLICIES_DIR = Path(__file__).parent.parent.parent / "infra" / "policies"

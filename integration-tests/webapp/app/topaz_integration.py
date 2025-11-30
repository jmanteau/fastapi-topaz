from __future__ import annotations

import sys
from pathlib import Path

import grpc
import httpx
from aserto.client.authorizer import AuthorizerClient
from fastapi import Request
from fastapi_topaz import (
    AuthorizerOptions,
    Identity,
    IdentityType,
    ResourceContext,
    TopazConfig,
)

from app.config import settings

# Monkey-patch AuthorizerClient for insecure local development
_original_init = AuthorizerClient.__init__


def _insecure_init(self, *, tenant_id=None, identity, options):
    """Custom init that uses insecure channel for local development."""
    self._tenant_id = tenant_id
    self._options = options
    from aserto.authorizer.v2.api import IdentityContext

    self._identity_context_field = IdentityContext(
        identity=identity.value or "",
        type=identity.type,
    )
    # Use insecure channel for local development
    self._channel = grpc.insecure_channel(target=options.url)
    from aserto.authorizer.v2 import authorizer_pb2_grpc

    self.client = authorizer_pb2_grpc.AuthorizerStub(self._channel)


# Apply monkey patch
AuthorizerClient.__init__ = _insecure_init

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
    import sys
    sys.stderr.write(f"[DEBUG] resource_context_provider called for {request.url.path}\n")
    sys.stderr.flush()
    context: ResourceContext = {}

    # Add path parameters
    if hasattr(request, "path_params") and request.path_params:
        sys.stderr.write(f"[DEBUG] Path params: {request.path_params}\n")
        sys.stderr.flush()
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
            sys.stderr.write(f"[DEBUG] Looking up document {doc_id}\n")
            sys.stderr.flush()
            db = SessionLocal()
            try:
                document = db.query(Document).filter(Document.id == doc_id).first()
                if document:
                    # Add document data to context for policy evaluation
                    context["owner_id"] = document.owner_id
                    context["is_public"] = document.is_public
                    sys.stderr.write(f"[DEBUG] Document {doc_id}: owner_id={document.owner_id}, current_user.sub={context.get('current_user', {}).get('sub')}\n")
                    sys.stderr.flush()

                    # Add shares data
                    shares = []
                    for share in document.shares:
                        shares.append({
                            "user_id": share.user_id,
                            "permission": share.permission,
                        })
                    context["shares"] = shares
                else:
                    sys.stderr.write(f"[DEBUG] Document {doc_id} NOT FOUND\n")
                    sys.stderr.flush()
            finally:
                db.close()
        except Exception as e:
            # If document fetch fails, continue without document data
            sys.stderr.write(f"[DEBUG] Exception fetching document: {e}\n")
            sys.stderr.flush()

    # Fetch folder data if this is a folder-related request
    if "/folders/" in request.url.path and "id" in request.path_params:
        sys.stderr.write(f"[DEBUG] Fetching folder data for {request.url.path}\n")
        sys.stderr.flush()
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
                    sys.stderr.write(f"[DEBUG] Folder {folder_id}: owner_id={folder.owner_id}, user_sub={context.get('current_user', {}).get('sub')}\n")
                    sys.stderr.flush()
                else:
                    sys.stderr.write(f"[DEBUG] Folder {folder_id} NOT FOUND\n")
                    sys.stderr.flush()
            finally:
                db.close()
        except Exception as e:
            # If folder fetch fails, continue without folder data
            sys.stderr.write(f"[DEBUG] ERROR fetching folder: {e}\n")
            sys.stderr.flush()
            pass

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
)

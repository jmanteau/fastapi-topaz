from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_topaz import require_policy_allowed
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Document, Share, SharePermission, User
from app.topaz_integration import topaz_config

router = APIRouter()


class ShareCreate(BaseModel):
    document_id: int
    user_id: str
    permission: SharePermission


class ShareResponse(BaseModel):
    id: int
    document_id: int
    user_id: str
    permission: str

    class Config:
        from_attributes = True


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_share(
    request: Request,
    data: ShareCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ShareResponse:
    """Share document with another user. Requires can_share permission (owner only)."""
    # First, verify document exists and fetch its data
    document = db.query(Document).filter(Document.id == data.document_id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Check if current user is owner (can_share permission)
    if document.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can share this document")

    # Optional: Topaz authorization check (if Topaz is available)
    try:
        client = topaz_config.create_client(request)

        # Get resource context from provider (includes user info, location)
        from app.topaz_integration import resource_context_provider
        resource_ctx = resource_context_provider(request)

        # Add document data for policy evaluation
        resource_ctx.update({
            "owner_id": document.owner_id,
            "is_public": document.is_public,
            "shares": [{"user_id": s.user_id, "permission": s.permission} for s in document.shares],
            "object_type": "document",
            "object_id": str(data.document_id),
            "relation": "can_share",
            "subject_type": "user",
        })

        decisions = client.decisions(
            policy_path=f"{topaz_config.policy_path_root}.check",
            decisions=("allowed",),
            policy_instance_name=topaz_config.policy_instance_name,
            policy_instance_label=topaz_config.policy_instance_label,
            resource_context=resource_ctx,
        )
        if not decisions.get("allowed", False):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied by policy")
    except HTTPException:
        raise
    except Exception as e:
        # If Topaz is unavailable, fall back to ownership check (already done above)
        import logging
        logging.warning(f"Topaz authorization check failed, using ownership fallback: {e}")

    # Verify target user exists
    target_user = db.query(User).filter(User.id == data.user_id).first()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check if share already exists
    existing_share = (
        db.query(Share)
        .filter(Share.document_id == data.document_id, Share.user_id == data.user_id)
        .first()
    )
    if existing_share:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Share already exists",
        )

    share = Share(
        document_id=data.document_id,
        user_id=data.user_id,
        permission=data.permission.value,
    )

    db.add(share)
    db.commit()
    db.refresh(share)

    return ShareResponse.model_validate(share)


@router.get("/document/{document_id}")
async def list_document_shares(
    document_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ShareResponse]:
    """List all shares for a document."""
    shares = db.query(Share).filter(Share.document_id == document_id).all()
    return [ShareResponse.model_validate(share) for share in shares]


@router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_share(
    share_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _: None = Depends(require_policy_allowed(topaz_config, "webapp.api.shares")),
):
    """Remove share."""
    share = db.query(Share).filter(Share.id == share_id).first()

    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")

    db.delete(share)
    db.commit()

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_topaz import require_policy_allowed, require_rebac_allowed
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Document, User
from app.topaz_integration import topaz_config

router = APIRouter()


class DocumentCreate(BaseModel):
    name: str
    content: str = ""
    folder_id: int | None = None
    is_public: bool = False


class DocumentUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    is_public: bool | None = None


class UserInfo(BaseModel):
    id: str
    name: str
    email: str

    class Config:
        from_attributes = True


class ShareInfo(BaseModel):
    user: UserInfo
    permission: str

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: int
    name: str
    content: str
    owner_id: str
    folder_id: int | None
    is_public: bool

    class Config:
        from_attributes = True


class PermissionsInfo(BaseModel):
    can_read: bool
    can_write: bool
    can_delete: bool
    can_share: bool
    is_owner: bool


class DocumentDetailResponse(BaseModel):
    id: int
    name: str
    content: str
    owner: UserInfo
    folder_id: int | None
    is_public: bool
    shares: list[ShareInfo]

    class Config:
        from_attributes = True


class DocumentListItem(BaseModel):
    id: int
    name: str
    content: str
    owner: UserInfo
    folder_id: int | None
    is_public: bool
    shares: list[ShareInfo]
    permissions: PermissionsInfo

    class Config:
        from_attributes = True


def _get_permissions(document: Document, user_id: str) -> PermissionsInfo:
    """Calculate user permissions for a document."""
    is_owner = document.owner_id == user_id
    user_share = next(
        (s for s in document.shares if s.user_id == user_id),
        None
    )
    return PermissionsInfo(
        can_read=is_owner or document.is_public or user_share is not None,
        can_write=is_owner or (user_share is not None and user_share.permission == "write"),
        can_delete=is_owner,
        can_share=is_owner,
        is_owner=is_owner,
    )


@router.get("")
async def list_documents(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[DocumentListItem]:
    """List all documents accessible to current user with owner and permissions."""
    documents = (
        db.query(Document)
        .filter(
            (Document.owner_id == current_user.id)
            | (Document.is_public == True)  # noqa: E712
            | (Document.shares.any(user_id=current_user.id))
        )
        .all()
    )

    return [
        DocumentListItem(
            id=doc.id,
            name=doc.name,
            content=doc.content,
            owner=UserInfo(id=doc.owner.id, name=doc.owner.name, email=doc.owner.email),
            folder_id=doc.folder_id,
            is_public=doc.is_public,
            shares=[
                ShareInfo(
                    user=UserInfo(id=s.user.id, name=s.user.name, email=s.user.email),
                    permission=s.permission,
                )
                for s in doc.shares
            ],
            permissions=_get_permissions(doc, current_user.id),
        )
        for doc in documents
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(
    request: Request,
    data: DocumentCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _: None = Depends(require_policy_allowed(topaz_config, "webapp.api.documents")),
) -> DocumentResponse:
    """Create new document. Requires POST.api.documents policy."""
    document = Document(
        name=data.name,
        content=data.content,
        owner_id=current_user.id,
        folder_id=data.folder_id,
        is_public=data.is_public,
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    return DocumentResponse.model_validate(document)


@router.get("/{id}")
async def get_document(
    id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DocumentDetailResponse:
    """Get document by ID with owner and permissions info."""
    # First check if document exists
    document = db.query(Document).filter(Document.id == id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Now check authorization (document exists, so resource_context_provider will have data)
    from fastapi_topaz import require_rebac_allowed
    await require_rebac_allowed(topaz_config, "document", "can_read")(request)

    # Build response with owner and shares
    return DocumentDetailResponse(
        id=document.id,
        name=document.name,
        content=document.content,
        owner=UserInfo(
            id=document.owner.id,
            name=document.owner.name,
            email=document.owner.email,
        ),
        folder_id=document.folder_id,
        is_public=document.is_public,
        shares=[
            ShareInfo(
                user=UserInfo(
                    id=share.user.id,
                    name=share.user.name,
                    email=share.user.email,
                ),
                permission=share.permission,
            )
            for share in document.shares
        ],
    )


@router.put("/{id}")
async def update_document(
    id: int,
    request: Request,
    data: DocumentUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _: None = Depends(require_rebac_allowed(topaz_config, "document", "can_write")),
) -> DocumentResponse:
    """Update document. Uses ReBAC check for can_write permission."""
    document = db.query(Document).filter(Document.id == id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if data.name is not None:
        document.name = data.name
    if data.content is not None:
        document.content = data.content
    if data.is_public is not None:
        document.is_public = data.is_public

    db.commit()
    db.refresh(document)

    return DocumentResponse.model_validate(document)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _: None = Depends(require_rebac_allowed(topaz_config, "document", "can_delete")),
):
    """Delete document. Uses ReBAC check for can_delete permission (owner only)."""
    document = db.query(Document).filter(Document.id == id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    db.delete(document)
    db.commit()


class PermissionsResponse(BaseModel):
    can_read: bool
    can_write: bool
    can_delete: bool
    can_share: bool
    is_owner: bool


@router.get("/{id}/permissions")
async def get_document_permissions(
    id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PermissionsResponse:
    """Get current user's effective permissions on a document."""
    document = db.query(Document).filter(Document.id == id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    is_owner = document.owner_id == current_user.id

    # Check each permission via policy
    # For simplicity, derive from ownership and shares
    user_share = next(
        (s for s in document.shares if s.user_id == current_user.id),
        None
    )

    can_read = is_owner or document.is_public or user_share is not None
    can_write = is_owner or (user_share and user_share.permission == "write")
    can_delete = is_owner
    can_share = is_owner

    return PermissionsResponse(
        can_read=can_read,
        can_write=can_write,
        can_delete=can_delete,
        can_share=can_share,
        is_owner=is_owner,
    )

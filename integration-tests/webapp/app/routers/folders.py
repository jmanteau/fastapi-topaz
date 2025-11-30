from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_topaz import require_policy_allowed
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Folder, User
from app.topaz_integration import topaz_config

router = APIRouter()


class FolderCreate(BaseModel):
    name: str
    parent_folder_id: int | None = None


class FolderUpdate(BaseModel):
    name: str


class FolderResponse(BaseModel):
    id: int
    name: str
    owner_id: str
    parent_folder_id: int | None

    class Config:
        from_attributes = True


@router.get("")
async def list_folders(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[FolderResponse]:
    """List all folders owned by current user."""
    folders = db.query(Folder).filter(Folder.owner_id == current_user.id).all()
    return [FolderResponse.model_validate(folder) for folder in folders]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_folder(
    request: Request,
    data: FolderCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _: None = Depends(require_policy_allowed(topaz_config, "webapp.api.folders")),
) -> FolderResponse:
    """Create new folder."""
    folder = Folder(
        name=data.name,
        owner_id=current_user.id,
        parent_folder_id=data.parent_folder_id,
    )

    db.add(folder)
    db.commit()
    db.refresh(folder)

    return FolderResponse.model_validate(folder)


@router.get("/{id}")
async def get_folder(
    id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _: None = Depends(require_policy_allowed(topaz_config, "webapp.api.folders")),
) -> FolderResponse:
    """Get folder by ID."""
    folder = db.query(Folder).filter(Folder.id == id).first()

    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    return FolderResponse.model_validate(folder)


@router.put("/{id}")
async def update_folder(
    id: int,
    request: Request,
    data: FolderUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _: None = Depends(require_policy_allowed(topaz_config, "webapp.api.folders")),
) -> FolderResponse:
    """Update folder."""
    folder = db.query(Folder).filter(Folder.id == id).first()

    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    folder.name = data.name
    db.commit()
    db.refresh(folder)

    return FolderResponse.model_validate(folder)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _: None = Depends(require_policy_allowed(topaz_config, "webapp.api.folders")),
):
    """Delete folder."""
    folder = db.query(Folder).filter(Folder.id == id).first()

    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    db.delete(folder)
    db.commit()

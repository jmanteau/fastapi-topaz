from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.routers.folders import FolderCreate, FolderResponse, FolderUpdate


def test_folder_create_minimal():
    """FolderCreate should accept minimal required fields."""
    data = FolderCreate(name="Documents")

    assert data.name == "Documents"
    assert data.parent_folder_id is None


def test_folder_create_with_parent():
    """FolderCreate should accept parent_folder_id."""
    data = FolderCreate(name="Subfolder", parent_folder_id=42)

    assert data.name == "Subfolder"
    assert data.parent_folder_id == 42


def test_folder_create_missing_name():
    """FolderCreate should require name field."""
    with pytest.raises(ValidationError) as exc_info:
        FolderCreate()

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("name",) for e in errors)


def test_folder_create_empty_name():
    """FolderCreate should accept empty string name."""
    data = FolderCreate(name="")
    assert data.name == ""


def test_folder_create_explicit_none_parent():
    """FolderCreate should accept None for parent_folder_id."""
    data = FolderCreate(name="Root", parent_folder_id=None)
    assert data.parent_folder_id is None


def test_folder_update_name():
    """FolderUpdate should update folder name."""
    data = FolderUpdate(name="Renamed Folder")

    assert data.name == "Renamed Folder"


def test_folder_update_missing_name():
    """FolderUpdate should require name field."""
    with pytest.raises(ValidationError) as exc_info:
        FolderUpdate()

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("name",) for e in errors)


def test_folder_update_empty_name():
    """FolderUpdate should accept empty string name."""
    data = FolderUpdate(name="")
    assert data.name == ""


def test_folder_response_from_dict():
    """FolderResponse should be created from dict."""
    data = {
        "id": 1,
        "name": "Documents",
        "owner_id": "user-123",
        "parent_folder_id": 42,
    }

    response = FolderResponse(**data)

    assert response.id == 1
    assert response.name == "Documents"
    assert response.owner_id == "user-123"
    assert response.parent_folder_id == 42


def test_folder_response_null_parent():
    """FolderResponse should handle null parent_folder_id."""
    data = {
        "id": 1,
        "name": "Root Folder",
        "owner_id": "user-123",
        "parent_folder_id": None,
    }

    response = FolderResponse(**data)

    assert response.parent_folder_id is None


def test_folder_response_missing_required_field():
    """FolderResponse should require all fields except parent_folder_id."""
    with pytest.raises(ValidationError) as exc_info:
        FolderResponse(
            id=1,
            name="Test",
            # Missing owner_id
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("owner_id",) for e in errors)


def test_folder_response_from_attributes_config():
    """FolderResponse should have from_attributes=True config."""
    assert FolderResponse.model_config.get("from_attributes") is True


def test_folder_response_type_validation():
    """FolderResponse should validate field types."""
    with pytest.raises(ValidationError):
        FolderResponse(
            id="not-an-int",
            name="Test",
            owner_id="user-123",
            parent_folder_id=None,
        )

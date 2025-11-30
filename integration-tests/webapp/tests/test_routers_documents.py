from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.routers.documents import (
    DocumentCreate,
    DocumentResponse,
    DocumentUpdate,
    doc_id_mapper,
)


def test_document_create_minimal():
    """DocumentCreate should accept minimal required fields."""
    data = DocumentCreate(name="test.txt")

    assert data.name == "test.txt"
    assert data.content == ""
    assert data.folder_id is None
    assert data.is_public is False


def test_document_create_full():
    """DocumentCreate should accept all fields."""
    data = DocumentCreate(
        name="document.pdf",
        content="Document content",
        folder_id=42,
        is_public=True,
    )

    assert data.name == "document.pdf"
    assert data.content == "Document content"
    assert data.folder_id == 42
    assert data.is_public is True


def test_document_create_missing_name():
    """DocumentCreate should require name field."""
    with pytest.raises(ValidationError) as exc_info:
        DocumentCreate()

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("name",) for e in errors)


def test_document_create_empty_name():
    """DocumentCreate should accept empty string name."""
    data = DocumentCreate(name="")
    assert data.name == ""


def test_document_create_null_folder():
    """DocumentCreate should accept None for folder_id."""
    data = DocumentCreate(name="test.txt", folder_id=None)
    assert data.folder_id is None


def test_document_update_all_fields():
    """DocumentUpdate should accept all optional fields."""
    data = DocumentUpdate(
        name="updated.txt",
        content="Updated content",
        is_public=True,
    )

    assert data.name == "updated.txt"
    assert data.content == "Updated content"
    assert data.is_public is True


def test_document_update_partial():
    """DocumentUpdate should allow partial updates."""
    data = DocumentUpdate(name="only_name.txt")

    assert data.name == "only_name.txt"
    assert data.content is None
    assert data.is_public is None


def test_document_update_empty():
    """DocumentUpdate should allow no fields (all None)."""
    data = DocumentUpdate()

    assert data.name is None
    assert data.content is None
    assert data.is_public is None


def test_document_update_only_is_public():
    """DocumentUpdate should allow updating only is_public."""
    data = DocumentUpdate(is_public=False)

    assert data.name is None
    assert data.content is None
    assert data.is_public is False


def test_document_response_from_dict():
    """DocumentResponse should be created from dict."""
    data = {
        "id": 1,
        "name": "test.txt",
        "content": "Content",
        "owner_id": "user-123",
        "folder_id": 42,
        "is_public": True,
    }

    response = DocumentResponse(**data)

    assert response.id == 1
    assert response.name == "test.txt"
    assert response.content == "Content"
    assert response.owner_id == "user-123"
    assert response.folder_id == 42
    assert response.is_public is True


def test_document_response_null_folder():
    """DocumentResponse should handle null folder_id."""
    data = {
        "id": 1,
        "name": "test.txt",
        "content": "Content",
        "owner_id": "user-123",
        "folder_id": None,
        "is_public": False,
    }

    response = DocumentResponse(**data)

    assert response.folder_id is None


def test_document_response_missing_required_field():
    """DocumentResponse should require all fields."""
    with pytest.raises(ValidationError) as exc_info:
        DocumentResponse(
            id=1,
            name="test.txt",
            # Missing content, owner_id, is_public
        )

    errors = exc_info.value.errors()
    assert len(errors) >= 2


def test_document_response_from_attributes_config():
    """DocumentResponse should have from_attributes=True config."""
    assert DocumentResponse.model_config.get("from_attributes") is True


def test_doc_id_mapper_with_id():
    """doc_id_mapper should extract id from request path params."""
    request = MagicMock()
    request.path_params = {"id": "123"}

    with patch("fastapi_topaz.get_request_context", return_value=request):
        result = doc_id_mapper()

        assert result == "123"


def test_doc_id_mapper_no_id():
    """doc_id_mapper should return empty string when id not in path params."""
    request = MagicMock()
    request.path_params = {"other": "value"}

    with patch("fastapi_topaz.get_request_context", return_value=request):
        result = doc_id_mapper()

        assert result == ""


def test_doc_id_mapper_no_request():
    """doc_id_mapper should return empty string when no request context."""
    with patch("fastapi_topaz.get_request_context", return_value=None):
        result = doc_id_mapper()

        assert result == ""


def test_doc_id_mapper_integer_id():
    """doc_id_mapper should handle integer id."""
    request = MagicMock()
    request.path_params = {"id": 456}

    with patch("fastapi_topaz.get_request_context", return_value=request):
        result = doc_id_mapper()

        assert result == 456

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models import Document, User


def test_create_user(db: Session):
    """Test user creation."""
    user = User(id="test-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    retrieved = db.query(User).filter(User.id == "test-1").first()
    assert retrieved is not None
    assert retrieved.email == "test@example.com"


def test_create_document(db: Session):
    """Test document creation."""
    user = User(id="test-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    doc = Document(
        name="Test Document",
        content="Test content",
        owner_id=user.id,
        is_public=False,
    )
    db.add(doc)
    db.commit()

    retrieved = db.query(Document).filter(Document.id == doc.id).first()
    assert retrieved is not None
    assert retrieved.name == "Test Document"
    assert retrieved.owner_id == user.id


def test_document_ownership(db: Session):
    """Test document ownership relationships."""
    user = User(id="owner-1", email="owner@example.com", name="Owner")
    db.add(user)
    db.commit()

    doc = Document(name="Owned Doc", content="Content", owner_id=user.id)
    db.add(doc)
    db.commit()

    assert doc.owner.id == user.id
    assert doc.owner.email == "owner@example.com"


def test_public_document_flag(db: Session):
    """Test public/private document flag."""
    user = User(id="user-1", email="user@example.com", name="User")
    db.add(user)
    db.commit()

    private_doc = Document(name="Private", content="Secret", owner_id=user.id, is_public=False)
    public_doc = Document(name="Public", content="Public info", owner_id=user.id, is_public=True)

    db.add_all([private_doc, public_doc])
    db.commit()

    assert private_doc.is_public is False
    assert public_doc.is_public is True


@pytest.mark.parametrize(
    "doc_name,content,is_public",
    [
        ("Document 1", "Content 1", False),
        ("Document 2", "Content 2", True),
        ("Document 3", "", False),
    ],
)
def test_document_variations(db: Session, doc_name: str, content: str, is_public: bool):
    """Test different document configurations."""
    user = User(id="user-1", email="user@example.com", name="User")
    db.add(user)
    db.commit()

    doc = Document(name=doc_name, content=content, owner_id=user.id, is_public=is_public)
    db.add(doc)
    db.commit()

    retrieved = db.query(Document).filter(Document.name == doc_name).first()
    assert retrieved is not None
    assert retrieved.content == content
    assert retrieved.is_public == is_public

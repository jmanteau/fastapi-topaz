from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Document, Folder, Share, SharePermission, User


def test_share_permission_enum_values():
    """SharePermission enum should have read and write values."""
    assert SharePermission.read.value == "read"
    assert SharePermission.write.value == "write"


def test_share_permission_enum_members():
    """SharePermission should contain exactly read and write members."""
    members = list(SharePermission)
    assert len(members) == 2
    assert SharePermission.read in members
    assert SharePermission.write in members


def test_user_creation(db: Session):
    """User should be created with required fields."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    assert user.id == "user-1"
    assert user.email == "test@example.com"
    assert user.name == "Test User"
    assert isinstance(user.created_at, datetime)


def test_user_email_unique_constraint(db: Session):
    """User email should be unique."""
    user1 = User(id="user-1", email="duplicate@example.com", name="User 1")
    db.add(user1)
    db.commit()

    user2 = User(id="user-2", email="duplicate@example.com", name="User 2")
    db.add(user2)

    with pytest.raises(IntegrityError):
        db.commit()


def test_user_relationships(db: Session):
    """User should have relationships to documents, folders, and shares."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    assert hasattr(user, "owned_documents")
    assert hasattr(user, "owned_folders")
    assert hasattr(user, "shares")
    assert isinstance(user.owned_documents, list)
    assert isinstance(user.owned_folders, list)
    assert isinstance(user.shares, list)


def test_folder_creation(db: Session):
    """Folder should be created with owner."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    folder = Folder(name="Documents", owner_id=user.id)
    db.add(folder)
    db.commit()

    assert folder.name == "Documents"
    assert folder.owner_id == user.id
    assert folder.parent_folder_id is None
    assert isinstance(folder.created_at, datetime)
    assert isinstance(folder.updated_at, datetime)


def test_folder_with_parent(db: Session):
    """Folder should support parent-child relationships."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    parent = Folder(name="Parent", owner_id=user.id)
    db.add(parent)
    db.commit()

    child = Folder(name="Child", owner_id=user.id, parent_folder_id=parent.id)
    db.add(child)
    db.commit()

    assert child.parent_folder_id == parent.id
    assert child.parent.id == parent.id
    assert len(parent.children) == 1
    assert parent.children[0].id == child.id


def test_folder_owner_relationship(db: Session):
    """Folder should have relationship to owner."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    folder = Folder(name="Test Folder", owner_id=user.id)
    db.add(folder)
    db.commit()

    assert folder.owner.id == user.id
    assert folder.owner.email == user.email


def test_document_creation(db: Session):
    """Document should be created with required fields."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    doc = Document(name="test.txt", content="Content", owner_id=user.id)
    db.add(doc)
    db.commit()

    assert doc.name == "test.txt"
    assert doc.content == "Content"
    assert doc.owner_id == user.id
    assert doc.is_public is False
    assert doc.folder_id is None
    assert isinstance(doc.created_at, datetime)
    assert isinstance(doc.updated_at, datetime)


def test_document_public_flag(db: Session):
    """Document should support public flag."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    doc = Document(name="public.txt", content="Public content", owner_id=user.id, is_public=True)
    db.add(doc)
    db.commit()

    assert doc.is_public is True


def test_document_in_folder(db: Session):
    """Document should support folder association."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    folder = Folder(name="Docs", owner_id=user.id)
    db.add(folder)
    db.commit()

    doc = Document(name="doc.txt", content="Content", owner_id=user.id, folder_id=folder.id)
    db.add(doc)
    db.commit()

    assert doc.folder_id == folder.id
    assert doc.folder.name == "Docs"
    assert len(folder.documents) == 1
    assert folder.documents[0].id == doc.id


def test_document_owner_relationship(db: Session):
    """Document should have relationship to owner."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    doc = Document(name="doc.txt", content="Content", owner_id=user.id)
    db.add(doc)
    db.commit()

    assert doc.owner.id == user.id
    assert doc.owner.email == user.email


def test_share_creation(db: Session):
    """Share should be created linking document and user."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    shared_with = User(id="user-2", email="other@example.com", name="Other User")
    db.add_all([user, shared_with])
    db.commit()

    doc = Document(name="shared.txt", content="Content", owner_id=user.id)
    db.add(doc)
    db.commit()

    share = Share(document_id=doc.id, user_id=shared_with.id, permission=SharePermission.read.value)
    db.add(share)
    db.commit()

    assert share.document_id == doc.id
    assert share.user_id == shared_with.id
    assert share.permission == "read"
    assert isinstance(share.created_at, datetime)


def test_share_with_write_permission(db: Session):
    """Share should support write permission."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    shared_with = User(id="user-2", email="other@example.com", name="Other User")
    db.add_all([user, shared_with])
    db.commit()

    doc = Document(name="shared.txt", content="Content", owner_id=user.id)
    db.add(doc)
    db.commit()

    share = Share(document_id=doc.id, user_id=shared_with.id, permission=SharePermission.write.value)
    db.add(share)
    db.commit()

    assert share.permission == "write"


def test_share_relationships(db: Session):
    """Share should have relationships to document and user."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    shared_with = User(id="user-2", email="other@example.com", name="Other User")
    db.add_all([user, shared_with])
    db.commit()

    doc = Document(name="shared.txt", content="Content", owner_id=user.id)
    db.add(doc)
    db.commit()

    share = Share(document_id=doc.id, user_id=shared_with.id, permission=SharePermission.read.value)
    db.add(share)
    db.commit()

    assert share.document.id == doc.id
    assert share.user.id == shared_with.id
    assert len(doc.shares) == 1
    assert len(shared_with.shares) == 1


def test_document_default_content(db: Session):
    """Document content should default to empty string."""
    user = User(id="user-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()

    doc = Document(name="empty.txt", owner_id=user.id)
    db.add(doc)
    db.commit()

    assert doc.content == ""

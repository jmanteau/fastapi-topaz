from __future__ import annotations

"""
Authorization test scenarios.

Note: These tests verify database models and business logic.
Integration tests with Topaz should be run against the running Docker environment.
"""

import pytest
from sqlalchemy.orm import Session

from app.models import Document, Share, SharePermission, User


@pytest.fixture
def alice(db: Session) -> User:
    """Create test user Alice."""
    user = User(id="alice-id", email="alice@example.com", name="Alice")
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def bob(db: Session) -> User:
    """Create test user Bob."""
    user = User(id="bob-id", email="bob@example.com", name="Bob")
    db.add(user)
    db.commit()
    return user


def test_scenario_1_alice_creates_document(db: Session, alice: User, bob: User):
    """
    Scenario: Alice creates private document.
    Expected: Alice owns document, Bob cannot see it.
    """
    doc = Document(name="Budget.xlsx", content="Confidential", owner_id=alice.id, is_public=False)
    db.add(doc)
    db.commit()

    assert doc.owner_id == alice.id
    assert doc.is_public is False

    # Bob shouldn't see document in query
    bob_docs = (
        db.query(Document)
        .filter((Document.owner_id == bob.id) | (Document.is_public == True))  # noqa: E712
        .all()
    )
    assert doc not in bob_docs


def test_scenario_2_alice_shares_with_bob_read(db: Session, alice: User, bob: User):
    """
    Scenario: Alice shares document with Bob (read permission).
    Expected: Bob can read but not modify.
    """
    doc = Document(name="Report.pdf", content="Report content", owner_id=alice.id)
    db.add(doc)
    db.commit()

    share = Share(document_id=doc.id, user_id=bob.id, permission=SharePermission.read.value)
    db.add(share)
    db.commit()

    bob_shares = db.query(Share).filter(Share.user_id == bob.id).all()
    assert len(bob_shares) == 1
    assert bob_shares[0].permission == "read"
    assert bob_shares[0].document_id == doc.id


def test_scenario_3_alice_makes_document_public(db: Session, alice: User, bob: User):
    """
    Scenario: Alice makes document public.
    Expected: All users can read.
    """
    doc = Document(name="Announcement.txt", content="Public info", owner_id=alice.id, is_public=True)
    db.add(doc)
    db.commit()

    public_docs = db.query(Document).filter(Document.is_public == True).all()  # noqa: E712
    assert doc in public_docs


def test_scenario_4_share_permissions(db: Session, alice: User, bob: User):
    """
    Scenario: Test different share permission levels.
    Expected: Can differentiate between read and write shares.
    """
    doc = Document(name="Shared Doc", content="Content", owner_id=alice.id)
    db.add(doc)
    db.commit()

    read_share = Share(document_id=doc.id, user_id=bob.id, permission=SharePermission.read.value)
    db.add(read_share)
    db.commit()

    shares = db.query(Share).filter(Share.document_id == doc.id).all()
    assert len(shares) == 1
    assert shares[0].permission == "read"

    # Update to write permission
    shares[0].permission = SharePermission.write.value
    db.commit()

    updated = db.query(Share).filter(Share.id == shares[0].id).first()
    assert updated.permission == "write"


def test_multiple_shares_on_document(db: Session, alice: User, bob: User):
    """Test document shared with multiple users."""
    charlie = User(id="charlie-id", email="charlie@example.com", name="Charlie")
    db.add(charlie)
    db.commit()

    doc = Document(name="Team Doc", content="Team content", owner_id=alice.id)
    db.add(doc)
    db.commit()

    bob_share = Share(document_id=doc.id, user_id=bob.id, permission=SharePermission.read.value)
    charlie_share = Share(
        document_id=doc.id, user_id=charlie.id, permission=SharePermission.write.value
    )
    db.add_all([bob_share, charlie_share])
    db.commit()

    shares = db.query(Share).filter(Share.document_id == doc.id).all()
    assert len(shares) == 2

    read_shares = [s for s in shares if s.permission == "read"]
    write_shares = [s for s in shares if s.permission == "write"]
    assert len(read_shares) == 1
    assert len(write_shares) == 1

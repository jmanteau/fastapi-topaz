from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_or_create_user
from app.models import User


@pytest.mark.asyncio
async def test_get_current_user_authenticated():
    """get_current_user should return User when session contains user data."""
    request = MagicMock()
    request.session = {
        "user": {
            "sub": "user-123",
            "email": "test@example.com",
            "name": "Test User",
        }
    }

    user = await get_current_user(request)

    assert user.id == "user-123"
    assert user.email == "test@example.com"
    assert user.name == "Test User"


@pytest.mark.asyncio
async def test_get_current_user_with_missing_name():
    """get_current_user should use email as name when name is missing."""
    request = MagicMock()
    request.session = {
        "user": {
            "sub": "user-456",
            "email": "noname@example.com",
        }
    }

    user = await get_current_user(request)

    assert user.id == "user-456"
    assert user.email == "noname@example.com"
    assert user.name == "noname@example.com"


@pytest.mark.asyncio
async def test_get_current_user_not_authenticated():
    """get_current_user should raise HTTPException when no user in session."""
    request = MagicMock()
    request.session = {}

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Not authenticated"


@pytest.mark.asyncio
async def test_get_current_user_empty_session():
    """get_current_user should raise HTTPException when session has no user key."""
    request = MagicMock()
    request.session = {"other_key": "value"}

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_or_create_user_creates_new_user(db: Session):
    """get_or_create_user should create new user if not exists."""
    userinfo = {
        "sub": "new-user-id",
        "email": "newuser@example.com",
        "name": "New User",
    }

    user = await get_or_create_user(db, userinfo)

    assert user.id == "new-user-id"
    assert user.email == "newuser@example.com"
    assert user.name == "New User"

    # Verify user was added to database
    db_user = db.query(User).filter(User.id == "new-user-id").first()
    assert db_user is not None
    assert db_user.email == "newuser@example.com"


@pytest.mark.asyncio
async def test_get_or_create_user_returns_existing_user(db: Session):
    """get_or_create_user should return existing user without creating duplicate."""
    existing_user = User(
        id="existing-user",
        email="existing@example.com",
        name="Existing User",
    )
    db.add(existing_user)
    db.commit()

    userinfo = {
        "sub": "existing-user",
        "email": "existing@example.com",
        "name": "Existing User",
    }

    user = await get_or_create_user(db, userinfo)

    assert user.id == "existing-user"
    assert user.email == "existing@example.com"

    # Verify only one user exists
    user_count = db.query(User).filter(User.id == "existing-user").count()
    assert user_count == 1


@pytest.mark.asyncio
async def test_get_or_create_user_with_missing_name(db: Session):
    """get_or_create_user should use email as name when name is missing."""
    userinfo = {
        "sub": "no-name-user",
        "email": "noname@example.com",
    }

    user = await get_or_create_user(db, userinfo)

    assert user.id == "no-name-user"
    assert user.email == "noname@example.com"
    assert user.name == "noname@example.com"


@pytest.mark.asyncio
async def test_get_or_create_user_commits_transaction(db: Session):
    """get_or_create_user should commit changes to database."""
    userinfo = {
        "sub": "commit-test-user",
        "email": "commit@example.com",
        "name": "Commit Test",
    }

    user = await get_or_create_user(db, userinfo)

    # Rollback and verify user persists (was committed)
    db.rollback()
    db_user = db.query(User).filter(User.id == "commit-test-user").first()
    assert db_user is not None

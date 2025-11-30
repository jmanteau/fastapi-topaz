from __future__ import annotations

from typing import Any

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User

oauth = OAuth()

oauth.register(
    name="authentik",
    client_id=settings.oidc_client_id,
    client_secret=settings.oidc_client_secret,
    server_metadata_url=f"{settings.oidc_issuer}.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


async def get_current_user(request: Request) -> User:
    """Get current authenticated user from session."""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return User(
        id=user_data["sub"],
        email=user_data["email"],
        name=user_data.get("name", user_data["email"]),
    )


async def get_or_create_user(db: Session, userinfo: dict[str, Any]) -> User:
    """Get or create user from OIDC userinfo."""
    user_id = userinfo["sub"]
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        user = User(
            id=user_id,
            email=userinfo["email"],
            name=userinfo.get("name", userinfo["email"]),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    return user

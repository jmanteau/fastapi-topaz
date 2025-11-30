from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import get_current_user, get_or_create_user, oauth
from app.config import settings
from app.database import get_db
from app.models import User
from app.routers import documents, folders, shares

app = FastAPI(title="FastAPI-Aserto Test Webapp")

# Middleware
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

# Static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Include routers
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(folders.router, prefix="/api/folders", tags=["folders"])
app.include_router(shares.router, prefix="/api/shares", tags=["shares"])


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Home page."""
    user = None
    try:
        user = await get_current_user(request)
    except Exception:
        pass

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "user": user},
    )


@app.get("/login")
async def login(request: Request):
    """Initiate OIDC login flow."""
    redirect_uri = request.url_for("auth_callback")
    return await oauth.authentik.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """OIDC callback endpoint."""
    token = await oauth.authentik.authorize_access_token(request)
    userinfo = token.get("userinfo")

    if not userinfo:
        return RedirectResponse("/login")

    # Store user in session
    request.session["user"] = {
        "sub": userinfo["sub"],
        "email": userinfo["email"],
        "name": userinfo.get("name", userinfo["email"]),
    }

    # Create user in database if doesn't exist
    db = next(get_db())
    await get_or_create_user(db, userinfo)

    return RedirectResponse("/")


@app.get("/logout")
async def logout(request: Request):
    """Logout user."""
    request.session.clear()
    return RedirectResponse("/")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/api/users")
async def list_users(request: Request):
    """List all users for sharing functionality."""
    try:
        current_user = await get_current_user(request)
    except Exception:
        return []

    db = next(get_db())
    users = db.query(User).filter(User.id != current_user.id).all()
    return [{"id": u.id, "name": u.name, "email": u.email} for u in users]

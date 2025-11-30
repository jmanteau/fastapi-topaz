# Authentication Tutorial

Learn to implement SSO authentication with OAuth2/OIDC in the example application.

**Time:** 30 minutes

## What You Will Learn

- OAuth2/OIDC authentication flow
- Protecting API endpoints with authentication
- Accessing user information in handlers
- Testing authentication

## Prerequisites

- Services running (`make up`)
- Authentik configured (`make tf-apply`)

## Part 1: Understanding the Login Flow

### Step 1: Try Logging In

Visit http://localhost:8000/login

What happens:
1. Redirect to Authentik (`http://localhost:9000/if/flow/...`)
2. Enter credentials (alice@example.com / password)
3. Redirect back to app (`http://localhost:8000/auth/callback?code=...&state=...`)
4. Session cookie created

The password never touches the application. OAuth uses redirects for security.

### Step 2: Examine the Session Cookie

In browser DevTools (Application > Cookies):

```
Name: session
Value: eyJ1c2VyIjp7InN1YiI6Ijk...
Domain: localhost
HttpOnly: true
```

The session contains user identity, signed to prevent tampering.

## Part 2: Creating an Authenticated Endpoint

### Step 3: Create a Protected Route

File: `webapp/app/routers/profile.py`

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from app.auth import get_current_user
from app.models import User

router = APIRouter()

@router.get("/profile")
async def get_profile(
    current_user: Annotated[User, Depends(get_current_user)]
):
    """Get current user's profile."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
    }
```

`Depends(get_current_user)` automatically:
- Checks if user is logged in
- Returns 401 if not
- Provides `User` object if authenticated

### Step 4: Register the Router

File: `webapp/app/main.py`

```python
from app.routers import profile
app.include_router(profile.router, tags=["profile"])
```

### Step 5: Test Your Endpoint

Rebuild and restart:
```bash
docker-compose build webapp
docker-compose up -d webapp
```

Test without authentication:
```bash
curl http://localhost:8000/profile
# Response: {"detail": "Not authenticated"}
# Status: 401 Unauthorized
```

Test with authentication:
```bash
curl -H "Cookie: session=$ALICE_SESSION_COOKIE" http://localhost:8000/profile
# Response: {"id": "...", "email": "alice@example.com", "name": "Alice Smith"}
```

## Part 3: Working With User Data

### Step 6: Create a Personal Resource

File: `webapp/app/routers/profile.py`

```python
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Document

@router.get("/profile/documents")
async def get_my_documents(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    """Get current user's documents."""
    documents = db.query(Document).filter(
        Document.owner_id == current_user.id
    ).all()

    return {
        "count": len(documents),
        "documents": [
            {"id": doc.id, "name": doc.name}
            for doc in documents
        ]
    }
```

Use `current_user.id` to filter data by authenticated user.

### Step 7: Test User Isolation

Create documents as Alice:
```bash
curl -X POST -H "Cookie: session=$ALICE_SESSION_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice Doc", "content": "test"}' \
  http://localhost:8000/api/documents
```

View as Alice:
```bash
curl -H "Cookie: session=$ALICE_SESSION_COOKIE" \
  http://localhost:8000/profile/documents
# Response: {"count": 1, "documents": [...]}
```

View as Bob:
```bash
curl -H "Cookie: session=$BOB_SESSION_COOKIE" \
  http://localhost:8000/profile/documents
# Response: {"count": 0, "documents": []}
```

Each user only sees their own data.

## Part 4: Understanding the Code

### Step 8: Examine get_current_user()

File: `webapp/app/auth.py`

```python
async def get_current_user(request: Request, db: Session) -> User:
    # 1. Get user data from session
    user_data = request.session.get("user")

    # 2. If no session, reject request
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 3. Look up user in database
    user = db.query(User).filter(User.id == user_data["sub"]).first()

    # 4. If user doesn't exist, create them (auto-registration)
    if not user:
        user = User(
            id=user_data["sub"],
            email=user_data["email"],
            name=user_data["name"]
        )
        db.add(user)
        db.commit()

    return user
```

### Step 9: Trace the Login Flow

File: `webapp/app/main.py`

Login endpoint:
```python
@app.get("/login")
async def login(request: Request):
    return await oauth.authentik.authorize_redirect(
        request,
        redirect_uri=settings.oidc_redirect_uri
    )
```

Callback endpoint:
```python
@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.authentik.authorize_access_token(request)
    userinfo = token.get('userinfo')

    request.session['user'] = {
        'sub': userinfo['sub'],
        'email': userinfo['email'],
        'name': userinfo['name']
    }

    return RedirectResponse(url="/")
```

## Part 5: Testing

### Step 10: Write a Test

File: `integration-tests/tests/test_profile.py`

```python
from tests.conftest import AuthenticatedClient

def test_get_profile(alice_client: AuthenticatedClient):
    """Test profile endpoint returns user data."""
    response = alice_client.get("/profile")

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "alice@example.com"

def test_profile_requires_auth(client):
    """Test profile endpoint rejects unauthenticated requests."""
    response = client.get("/profile")
    assert response.status_code == 401
```

Run tests:
```bash
cd integration-tests
uv run pytest tests/test_profile.py -v
```

## Summary

| Concept | Description |
|---------|-------------|
| OAuth/OIDC Flow | Redirect to IdP, authenticate, return with code, exchange for tokens |
| Session Management | Signed cookies store user identity |
| Protected Endpoints | `Depends(get_current_user)` provides authentication |
| User Context | Access `current_user.id`, `current_user.email` in handlers |

## Next Steps

- [Authorization Tutorial](03-authorization.md) - Add policy-based authorization
- [SSO Concepts](../../explanation/sso-concepts.md) - Deep dive into OIDC
- [OIDC Reference](../../reference/oidc.md) - Configuration options

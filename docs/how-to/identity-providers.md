# How-To: Configure Identity Providers

This guide shows how to extract user identity from different authentication methods.

## JWT Bearer Tokens

```python
import jwt
from fastapi import Request
from fastapi_topaz import Identity, IdentityType, TopazConfig

def jwt_identity_provider(request: Request) -> Identity:
    """Extract identity from JWT Bearer token."""
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return Identity(type=IdentityType.IDENTITY_TYPE_NONE)

    token = auth_header.replace("Bearer ", "")

    try:
        # Decode and verify JWT (use your secret/public key)
        payload = jwt.decode(token, "your-secret", algorithms=["HS256"])
        return Identity(
            type=IdentityType.IDENTITY_TYPE_SUB,
            value=payload["sub"],
        )
    except jwt.InvalidTokenError:
        return Identity(type=IdentityType.IDENTITY_TYPE_NONE)

config = TopazConfig(
    identity_provider=jwt_identity_provider,
    ...
)
```

## Session-Based (Cookies)

```python
from fastapi import Request
from fastapi_topaz import Identity, IdentityType

def session_identity_provider(request: Request) -> Identity:
    """Extract identity from session cookie."""
    user_data = request.session.get("user")

    if not user_data:
        return Identity(type=IdentityType.IDENTITY_TYPE_NONE)

    return Identity(
        type=IdentityType.IDENTITY_TYPE_SUB,
        value=user_data["sub"],
    )
```

## OAuth2 / OIDC

```python
from fastapi import Request
from fastapi_topaz import Identity, IdentityType

def oidc_identity_provider(request: Request) -> Identity:
    """Extract identity from OIDC userinfo in request state."""
    # Assumes you've already validated the token and stored userinfo
    user = getattr(request.state, "user", None)

    if not user:
        return Identity(type=IdentityType.IDENTITY_TYPE_NONE)

    return Identity(
        type=IdentityType.IDENTITY_TYPE_SUB,
        value=user.get("sub"),
    )
```

## API Keys

```python
from fastapi import Request
from fastapi_topaz import Identity, IdentityType

# Mapping of API keys to user IDs
API_KEYS = {
    "sk_live_abc123": "service-account-1",
    "sk_live_def456": "service-account-2",
}

def api_key_identity_provider(request: Request) -> Identity:
    """Extract identity from API key header."""
    api_key = request.headers.get("X-API-Key")

    if not api_key or api_key not in API_KEYS:
        return Identity(type=IdentityType.IDENTITY_TYPE_NONE)

    return Identity(
        type=IdentityType.IDENTITY_TYPE_SUB,
        value=API_KEYS[api_key],
    )
```

## Multiple Authentication Methods

```python
from fastapi import Request
from fastapi_topaz import Identity, IdentityType

def multi_auth_identity_provider(request: Request) -> Identity:
    """Try multiple authentication methods in order."""

    # 1. Try Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        try:
            payload = decode_jwt(token)
            return Identity(
                type=IdentityType.IDENTITY_TYPE_SUB,
                value=payload["sub"],
            )
        except Exception:
            pass

    # 2. Try API key
    api_key = request.headers.get("X-API-Key")
    if api_key and api_key in API_KEYS:
        return Identity(
            type=IdentityType.IDENTITY_TYPE_SUB,
            value=API_KEYS[api_key],
        )

    # 3. Try session
    user = request.session.get("user")
    if user:
        return Identity(
            type=IdentityType.IDENTITY_TYPE_SUB,
            value=user["sub"],
        )

    # No authentication found
    return Identity(type=IdentityType.IDENTITY_TYPE_NONE)
```

## Using MANUAL Identity Type

For cases where you don't want Topaz to look up the user in the directory:

```python
def manual_identity_provider(request: Request) -> Identity:
    """Use MANUAL type to skip directory lookup."""
    user_id = request.headers.get("X-User-ID")

    if not user_id:
        return Identity(type=IdentityType.IDENTITY_TYPE_NONE)

    # MANUAL type passes identity value directly to policy
    # without looking up user in Topaz directory
    return Identity(
        type=IdentityType.IDENTITY_TYPE_MANUAL,
        value=user_id,
    )
```

## See Also

- [API Reference](../reference/api.md) - TopazConfig configuration
- [Authorization Models](../explanation/authorization-models.md) - RBAC/ABAC/ReBAC concepts

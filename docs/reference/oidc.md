# OIDC Reference

OAuth2/OpenID Connect configuration for authentication.

## OIDC Flow

```
1. User visits /login
2. Redirect to Identity Provider (IdP)
3. User authenticates at IdP
4. IdP redirects to /auth/callback with code
5. App exchanges code for tokens
6. App extracts user info from ID token
7. Session created with user identity
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OIDC_ISSUER` | Yes | IdP issuer URL |
| `OIDC_CLIENT_ID` | Yes | OAuth2 client ID |
| `OIDC_CLIENT_SECRET` | Yes | OAuth2 client secret |
| `OIDC_REDIRECT_URI` | Yes | Callback URL |
| `OIDC_SCOPES` | No | Space-separated scopes (default: `openid email profile`) |

### FastAPI Setup with Authlib

```python
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config

config = Config('.env')

oauth = OAuth()
oauth.register(
    name='authentik',
    client_id=config('OIDC_CLIENT_ID'),
    client_secret=config('OIDC_CLIENT_SECRET'),
    server_metadata_url=f"{config('OIDC_ISSUER')}/.well-known/openid-configuration",
    client_kwargs={'scope': 'openid email profile'},
)

@app.get("/login")
async def login(request: Request):
    return await oauth.authentik.authorize_redirect(
        request, config('OIDC_REDIRECT_URI')
    )

@app.get("/auth/callback")
async def callback(request: Request):
    token = await oauth.authentik.authorize_access_token(request)
    userinfo = token.get('userinfo')
    request.session['user'] = {
        'sub': userinfo['sub'],
        'email': userinfo['email'],
        'name': userinfo.get('name', userinfo['email']),
    }
    return RedirectResponse(url="/")
```

## Token Claims

### ID Token

| Claim | Type | Description |
|-------|------|-------------|
| `sub` | string | Subject identifier (user ID) |
| `email` | string | User email address |
| `name` | string | Display name |
| `preferred_username` | string | Username |
| `iss` | string | Issuer URL |
| `aud` | string | Audience (client ID) |
| `exp` | number | Expiration timestamp |
| `iat` | number | Issued at timestamp |

### Access Token

Used for API calls to IdP (user info endpoint, etc.). Not typically decoded by the application.

## Session Storage

### Cookie-Based (Recommended)

```python
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(
    SessionMiddleware,
    secret_key=config('SESSION_SECRET'),
    max_age=86400,  # 24 hours
    https_only=True,  # Production only
    same_site='lax',
)
```

### Redis-Based (Scale-Out)

```python
from starsessions import SessionMiddleware
from starsessions.backends.redis import RedisBackend

app.add_middleware(
    SessionMiddleware,
    backend=RedisBackend('redis://localhost'),
)
```

## Identity Provider Configuration

### Authentik

1. Create OAuth2/OpenID Provider
2. Configure:
   - Client Type: Confidential
   - Redirect URIs: `http://localhost:8000/auth/callback`
   - Scopes: `openid email profile`

### Keycloak

1. Create OpenID Connect Client
2. Configure:
   - Access Type: confidential
   - Valid Redirect URIs: `http://localhost:8000/auth/callback`
   - Standard Flow Enabled: ON

### Auth0

1. Create Regular Web Application
2. Configure:
   - Allowed Callback URLs: `http://localhost:8000/auth/callback`
   - Allowed Logout URLs: `http://localhost:8000`

## Integration with FastAPI-Topaz

Extract identity from session for authorization:

```python
from fastapi import Request
from fastapi_topaz import Identity, IdentityType, TopazConfig

def identity_provider(request: Request) -> Identity:
    user = request.session.get('user')
    if not user:
        return Identity(type=IdentityType.IDENTITY_TYPE_NONE)
    return Identity(
        type=IdentityType.IDENTITY_TYPE_SUB,
        value=user['sub'],
    )

topaz_config = TopazConfig(
    ...
    identity_provider=identity_provider,
)
```

## Security Considerations

| Concern | Recommendation |
|---------|---------------|
| Session secret | Use cryptographically random string (32+ bytes) |
| HTTPS | Always use HTTPS in production |
| Cookie flags | Set `HttpOnly`, `Secure`, `SameSite=Lax` |
| Token validation | Validate `iss`, `aud`, `exp` claims |
| State parameter | Use to prevent CSRF (Authlib handles this) |

## See Also

- [Authentication Tutorial](../tutorials/example-app/02-authentication.md) - Step-by-step guide
- [SSO Concepts](../explanation/sso-concepts.md) - Architecture explanation
- [Authentik Setup](../how-to/example-app/authentik-setup.md) - Configuration guide

"""
Tests for TopazMiddleware.

TopazMiddleware provides automatic authorization for all routes by checking policies
before requests reach route handlers. This is an alternative to per-route dependencies.

Test organization:
- TestTopazMiddleware: Core middleware allow/deny behavior and policy path generation
- TestExcludePaths: Regex-based path exclusion patterns
- TestExcludeMethods: HTTP method exclusion (OPTIONS, HEAD by default)
- TestSkipMiddlewareDecorator: @skip_middleware route decorator
- TestSkipMiddlewareDependency: SkipMiddleware dependency for routers
- TestOnMissingIdentity: Handling unauthenticated requests
- TestOnDenied: Custom denial response handlers
- TestMiddlewareWithCache: Decision caching integration
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from fastapi_topaz import (
    DecisionCache,
    SkipMiddleware,
    TopazConfig,
    TopazMiddleware,
    skip_middleware,
)


@pytest.fixture
def authorizer_options():
    """Topaz authorizer connection options for testing."""
    return AuthorizerOptions(url="localhost:8282", tenant_id="test", api_key="key")


@pytest.fixture
def identity_provider():
    """Identity provider that returns a fixed user identity."""
    return lambda req: Identity(type=IdentityType.IDENTITY_TYPE_SUB, value="user-123")


@pytest.fixture
def topaz_config(authorizer_options, identity_provider):
    """Standard TopazConfig for middleware testing."""
    return TopazConfig(
        authorizer_options=authorizer_options,
        policy_path_root="testapp",
        identity_provider=identity_provider,
        policy_instance_name="test-policy",
    )


@pytest.fixture
def mock_client():
    """Mock authorizer client that allows all requests."""
    client = Mock()
    client.decisions = AsyncMock(return_value={"allowed": True})
    return client


@pytest.fixture
def mock_client_denied():
    """Mock authorizer client that denies all requests."""
    client = Mock()
    client.decisions = AsyncMock(return_value={"allowed": False})
    return client


@pytest.fixture
def patch_client(monkeypatch, mock_client):
    """Patch TopazConfig to use mock_client (allows all)."""
    monkeypatch.setattr(TopazConfig, "create_client", lambda self, req: mock_client)
    return mock_client


@pytest.fixture
def patch_client_denied(monkeypatch, mock_client_denied):
    """Patch TopazConfig to use mock_client_denied (denies all)."""
    monkeypatch.setattr(TopazConfig, "create_client", lambda self, req: mock_client_denied)
    return mock_client_denied


class TestTopazMiddleware:
    """
    Core middleware allow/deny behavior.

    TopazMiddleware intercepts requests before they reach route handlers,
    checks authorization via the configured policy, and returns 403 on denial.
    """

    def test_allows_when_policy_returns_true(self, topaz_config, patch_client):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config)

        @app.get("/documents")
        def route():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/documents")
        assert response.status_code == 200

    def test_denies_when_policy_returns_false(self, topaz_config, patch_client_denied):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config)

        @app.get("/documents")
        def route():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/documents")
        assert response.status_code == 403
        assert response.json() == {"detail": "Forbidden"}

    def test_generates_correct_policy_path(self, topaz_config, patch_client):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config)

        @app.get("/documents/{doc_id}")
        def route(doc_id: int):
            return {"id": doc_id}

        client = TestClient(app)
        client.get("/documents/123")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["policy_path"] == "testapp.GET.documents.__doc_id"

    def test_includes_path_params_in_context(self, topaz_config, patch_client):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config)

        @app.get("/docs/{doc_id}/sections/{section_id}")
        def route(doc_id: int, section_id: int):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/docs/123/sections/456")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["doc_id"] == "123"
        assert call_kwargs["resource_context"]["section_id"] == "456"


class TestExcludePaths:
    """
    Regex-based path exclusion from authorization.

    exclude_paths accepts a list of regex patterns. Matching paths bypass
    authorization entirely (useful for health checks, docs, public assets).
    """

    def test_excludes_exact_path(self, topaz_config, patch_client_denied):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config, exclude_paths=[r"^/health$"])

        @app.get("/health")
        def health():
            return {"status": "healthy"}

        @app.get("/documents")
        def docs():
            return {"status": "ok"}

        client = TestClient(app)
        # /health excluded - should pass even with denied policy
        assert client.get("/health").status_code == 200
        # /documents not excluded - should be denied
        assert client.get("/documents").status_code == 403

    def test_excludes_wildcard_path(self, topaz_config, patch_client_denied):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config, exclude_paths=[r"^/docs.*"])

        @app.get("/docs")
        def docs_root():
            return {"status": "ok"}

        @app.get("/docs/openapi.json")
        def openapi():
            return {}

        client = TestClient(app)
        assert client.get("/docs").status_code == 200
        assert client.get("/docs/openapi.json").status_code == 200


class TestExcludeMethods:
    """
    HTTP method exclusion from authorization.

    By default, OPTIONS and HEAD methods are excluded. This can be customized
    via the exclude_methods parameter.
    """

    def test_default_excludes_options_and_head(self, topaz_config, patch_client_denied):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config)

        @app.api_route("/test", methods=["GET", "OPTIONS", "HEAD"])
        def route():
            return {"status": "ok"}

        client = TestClient(app)
        assert client.options("/test").status_code == 200
        assert client.head("/test").status_code == 200
        assert client.get("/test").status_code == 403

    def test_custom_exclude_methods(self, topaz_config, patch_client_denied):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config, exclude_methods=["GET"])

        @app.get("/test")
        def get_route():
            return {"status": "ok"}

        @app.post("/test")
        def post_route():
            return {"status": "ok"}

        client = TestClient(app)
        assert client.get("/test").status_code == 200  # Excluded
        assert client.post("/test").status_code == 403  # Not excluded


class TestSkipMiddlewareDecorator:
    """
    @skip_middleware decorator for individual routes.

    Apply @skip_middleware to route functions to bypass authorization
    for specific endpoints while keeping middleware active for others.
    """

    def test_skips_decorated_route(self, topaz_config, patch_client_denied):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config)

        @app.get("/public")
        @skip_middleware
        def public_route():
            return {"status": "public"}

        @app.get("/protected")
        def protected_route():
            return {"status": "protected"}

        client = TestClient(app)
        assert client.get("/public").status_code == 200
        assert client.get("/protected").status_code == 403


class TestSkipMiddlewareDependency:
    """
    SkipMiddleware dependency for router-level exclusion.

    Add Depends(SkipMiddleware) to a router's dependencies to skip authorization
    for all routes in that router (useful for public API sections).
    """

    def test_skips_router_with_dependency(self, topaz_config, patch_client_denied):
        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config)

        public_router = APIRouter(prefix="/public", dependencies=[Depends(SkipMiddleware)])

        @public_router.get("/status")
        def public_status():
            return {"status": "ok"}

        @app.get("/protected")
        def protected():
            return {"status": "protected"}

        app.include_router(public_router)

        client = TestClient(app)
        assert client.get("/public/status").status_code == 200
        assert client.get("/protected").status_code == 403


class TestOnMissingIdentity:
    """
    Handling requests with no identity (unauthenticated users).

    on_missing_identity controls behavior when identity_provider returns None:
    - "deny": Return 401 Unauthorized
    - "anonymous": Proceed with anonymous identity (let policy decide)
    """

    def test_deny_returns_401(self, authorizer_options, patch_client):
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=lambda req: None,  # Returns None
            policy_instance_name="test",
        )

        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=config, on_missing_identity="deny")

        @app.get("/test")
        def route():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 401
        assert response.json() == {"detail": "Unauthorized"}

    def test_anonymous_passes_to_policy(self, authorizer_options, patch_client):
        # When on_missing_identity="anonymous", middleware uses anonymous identity
        # but check_decision still uses config's identity_provider
        # So we need an identity_provider that returns anonymous identity
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=lambda req: Identity(type=IdentityType.IDENTITY_TYPE_NONE, value="anonymous"),
            policy_instance_name="test",
        )

        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=config, on_missing_identity="anonymous")

        @app.get("/test")
        def route():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200  # Policy allowed with anonymous identity


class TestOnDenied:
    """
    Custom denial response handlers.

    on_denied allows customizing the 403 response (e.g., to include error codes,
    redirect URLs, or audit information).
    """

    def test_custom_denied_response(self, topaz_config, patch_client_denied):
        def custom_handler(request: Request, policy_path: str):
            return JSONResponse(
                status_code=403,
                content={"error": "access_denied", "policy": policy_path},
            )

        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config, on_denied=custom_handler)

        @app.get("/documents")
        def route():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/documents")
        assert response.status_code == 403
        assert response.json()["error"] == "access_denied"
        assert response.json()["policy"] == "testapp.GET.documents"


class TestMiddlewareWithCache:
    """
    Middleware integration with decision caching.

    When TopazConfig has a decision_cache, repeated requests with the same
    authorization context use cached results instead of calling the authorizer.
    """

    def test_caches_decisions(self, authorizer_options, identity_provider, monkeypatch):
        call_count = [0]

        def mock_create_client(self, req):
            call_count[0] += 1
            mock = Mock()
            mock.decisions = AsyncMock(return_value={"allowed": True})
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            decision_cache=DecisionCache(ttl_seconds=60),
        )

        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=config)

        @app.get("/test")
        def route():
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/test")
        assert call_count[0] == 1

        client.get("/test")
        assert call_count[0] == 1  # Cached, no additional call


class TestMiddlewareErrorHandling:
    """
    Middleware behavior when authorizer is unavailable.

    When authorization errors occur, the middleware defaults to denying access (403)
    rather than propagating the error (500). This is fail-safe behavior.
    Use circuit breaker for more sophisticated error handling strategies.
    """

    def test_connection_error_denies_access(self, topaz_config, monkeypatch):
        """Connection errors result in 403 (fail-safe denial) without circuit breaker."""

        def failing_client(self, req):
            mock = Mock()
            mock.decisions = AsyncMock(side_effect=ConnectionError("authorizer unreachable"))
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", failing_client)

        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config)

        @app.get("/test")
        def route():
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test")
        # Middleware fails safe - denies access when authorizer unavailable
        assert response.status_code == 403

    def test_timeout_error_denies_access(self, topaz_config, monkeypatch):
        """Timeout errors result in 403 (fail-safe denial) without circuit breaker."""
        import asyncio

        def timeout_client(self, req):
            mock = Mock()
            mock.decisions = AsyncMock(side_effect=asyncio.TimeoutError("request timed out"))
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", timeout_client)

        app = FastAPI()
        app.add_middleware(TopazMiddleware, config=topaz_config)

        @app.get("/test")
        def route():
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test")
        # Middleware fails safe - denies access when authorizer unavailable
        assert response.status_code == 403

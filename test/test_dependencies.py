"""
Tests for fastapi-topaz dependencies.

This module tests the core authorization dependencies that integrate FastAPI with Topaz.
These dependencies are the primary API for adding authorization to FastAPI routes.

Test organization:
- TestTopazConfig: Configuration class initialization and methods
- TestPolicyPathHeuristic: URL-to-policy path conversion logic
- TestResolvePolicyPath: Full policy path resolution
- TestRequirePolicyAuto: Auto-resolving policy paths from routes
- TestRequirePolicyAllowed: Explicit policy path authorization
- TestRequireRebacAllowed: Relationship-based access control checks
- TestGetAuthorizedResource: Fetch-then-authorize pattern
- TestFilterAuthorizedResources: Batch authorization filtering
- TestAsyncRoutes: Async route compatibility verification
- TestDecisionCache: TTL-based caching behavior
- TestTopazConfigWithCache: Caching integration tests
- TestConcurrentFilter: Concurrent authorization performance
- TestIsAllowed: Non-raising permission checks
- TestCheckRelation: Non-raising ReBAC checks
- TestCheckRelations: Batch permission checks
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock

import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from fastapi_topaz import (
    DecisionCache,
    HierarchyResult,
    TopazConfig,
    filter_authorized_resources,
    get_authorized_resource,
    require_policy_allowed,
    require_policy_auto,
    require_rebac_allowed,
    require_rebac_hierarchy,
)
from fastapi_topaz.dependencies import _policy_path_heuristic, _resolve_policy_path


@pytest.fixture
def authorizer_options():
    """Create test AuthorizerOptions."""
    return AuthorizerOptions(
        url="localhost:8282",
        tenant_id="test-tenant",
        api_key="test-key",
    )


@pytest.fixture
def mock_client():
    """Create a mock async AuthorizerClient."""
    client = Mock()
    client.decisions = AsyncMock(return_value={"allowed": True})
    return client


@pytest.fixture
def mock_client_denied():
    """Create a mock async AuthorizerClient that denies access."""
    client = Mock()
    client.decisions = AsyncMock(return_value={"allowed": False})
    return client


@pytest.fixture
def identity_provider():
    """Create a simple identity provider."""
    return lambda req: Identity(type=IdentityType.IDENTITY_TYPE_SUB, value="user-123")


@pytest.fixture
def topaz_config(authorizer_options, identity_provider):
    """Create a test TopazConfig."""
    return TopazConfig(
        authorizer_options=authorizer_options,
        policy_path_root="testapp",
        identity_provider=identity_provider,
        policy_instance_name="test-policy",
    )


@pytest.fixture
def patch_client(monkeypatch, mock_client):
    """Patch TopazConfig.create_client to return mock."""
    monkeypatch.setattr(TopazConfig, "create_client", lambda self, req: mock_client)
    return mock_client


@pytest.fixture
def patch_client_denied(monkeypatch, mock_client_denied):
    """Patch TopazConfig.create_client to return denying mock."""
    monkeypatch.setattr(TopazConfig, "create_client", lambda self, req: mock_client_denied)
    return mock_client_denied


class TestTopazConfig:
    """
    TopazConfig initialization and configuration.

    TopazConfig is the central configuration object that holds authorizer connection
    settings, identity provider, and optional features like caching and context providers.
    """

    def test_creation_with_required_params(self, authorizer_options, identity_provider):
        """TopazConfig should be created with required parameters."""
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="myapp",
            identity_provider=identity_provider,
            policy_instance_name="my-policy",
        )
        assert config.policy_path_root == "myapp"
        assert config.policy_instance_name == "my-policy"

    def test_policy_instance_label_defaults_to_name(self, authorizer_options, identity_provider):
        """policy_instance_label should default to policy_instance_name."""
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="myapp",
            identity_provider=identity_provider,
            policy_instance_name="my-policy",
        )
        assert config.policy_instance_label == "my-policy"

    def test_policy_instance_label_can_be_overridden(self, authorizer_options, identity_provider):
        """policy_instance_label can be set explicitly."""
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="myapp",
            identity_provider=identity_provider,
            policy_instance_name="my-policy",
            policy_instance_label="custom-label",
        )
        assert config.policy_instance_label == "custom-label"

    def test_resource_context_provider_optional(self, authorizer_options, identity_provider):
        """resource_context_provider should be optional."""
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="myapp",
            identity_provider=identity_provider,
            policy_instance_name="my-policy",
        )
        assert config.resource_context_provider is None

    def test_resource_context_provider_can_be_set(self, authorizer_options, identity_provider):
        """resource_context_provider can be set."""

        def ctx_provider(req):
            return {"tenant": "acme"}

        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="myapp",
            identity_provider=identity_provider,
            policy_instance_name="my-policy",
            resource_context_provider=ctx_provider,
        )
        assert config.resource_context_provider is ctx_provider

    def test_policy_path_for_basic(self, topaz_config):
        """policy_path_for should generate path from method and route."""
        path = topaz_config.policy_path_for("GET", "/documents")
        assert path == "testapp.GET.documents"

    def test_policy_path_for_with_params(self, topaz_config):
        """policy_path_for should handle path parameters."""
        path = topaz_config.policy_path_for("PUT", "/documents/{id}")
        assert path == "testapp.PUT.documents.__id"

    def test_policy_path_for_nested_params(self, topaz_config):
        """policy_path_for should handle nested path parameters."""
        path = topaz_config.policy_path_for("GET", "/users/{user_id}/docs/{doc_id}")
        assert path == "testapp.GET.users.__user_id.docs.__doc_id"


class TestPolicyPathHeuristic:
    """
    URL path to policy path segment conversion.

    Converts URL paths like "/documents/{id}" to policy segments like ".documents.__id".
    Path parameters are prefixed with "__" to create valid Rego identifiers.
    """

    def test_root_path(self):
        """Root path should return empty string."""
        assert _policy_path_heuristic("/") == ""

    def test_empty_path(self):
        """Empty path should return empty string."""
        assert _policy_path_heuristic("") == ""

    def test_simple_path(self):
        """Simple path should be converted."""
        assert _policy_path_heuristic("/documents") == ".documents"

    def test_multi_segment_path(self):
        """Multi-segment path should be converted."""
        assert _policy_path_heuristic("/api/v1/documents") == ".api.v1.documents"

    def test_path_with_single_param(self):
        """Path with single parameter should convert param to __param."""
        assert _policy_path_heuristic("/documents/{id}") == ".documents.__id"

    def test_path_with_multiple_params(self):
        """Path with multiple parameters should convert all."""
        assert _policy_path_heuristic("/users/{user_id}/docs/{doc_id}") == ".users.__user_id.docs.__doc_id"

    def test_path_without_leading_slash(self):
        """Path without leading slash should work."""
        assert _policy_path_heuristic("documents/{id}") == ".documents.__id"

    def test_path_with_trailing_slash(self):
        """Path with trailing slash should work."""
        assert _policy_path_heuristic("/documents/") == ".documents"


class TestResolvePolicyPath:
    """
    Full policy path resolution from root, method, and URL path.

    Combines policy_path_root (e.g., "myapp") with HTTP method and URL path
    to create complete policy paths like "myapp.GET.documents.__id".
    """

    def test_basic_path(self):
        """Should combine root, method, and path."""
        assert _resolve_policy_path("myapp", "GET", "/documents") == "myapp.GET.documents"

    def test_root_path(self):
        """Root path should work."""
        assert _resolve_policy_path("myapp", "GET", "/") == "myapp.GET"

    def test_with_params(self):
        """Should handle path parameters."""
        assert _resolve_policy_path("myapp", "POST", "/docs/{id}") == "myapp.POST.docs.__id"

    def test_nested_paths(self):
        """Should handle nested paths with multiple params."""
        result = _resolve_policy_path("myapp", "DELETE", "/users/{uid}/posts/{pid}")
        assert result == "myapp.DELETE.users.__uid.posts.__pid"

    def test_different_methods(self):
        """Different methods should produce different paths."""
        assert _resolve_policy_path("app", "GET", "/items") == "app.GET.items"
        assert _resolve_policy_path("app", "POST", "/items") == "app.POST.items"
        assert _resolve_policy_path("app", "PUT", "/items") == "app.PUT.items"
        assert _resolve_policy_path("app", "DELETE", "/items") == "app.DELETE.items"


class TestRequirePolicyAuto:
    """
    Auto-resolving policy paths from FastAPI route definitions.

    require_policy_auto automatically derives the policy path from the route's
    HTTP method and URL pattern, eliminating the need to specify policy paths manually.
    """

    def test_auto_resolves_basic_path(self, topaz_config, patch_client):
        """Should auto-resolve policy path from route."""
        app = FastAPI()

        @app.get("/documents")
        def route(request: Request, _=Depends(require_policy_auto(topaz_config))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/documents")
        assert response.status_code == 200

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["policy_path"] == "testapp.GET.documents"

    def test_auto_resolves_path_with_params(self, topaz_config, patch_client):
        """Should auto-resolve path with parameters."""
        app = FastAPI()

        @app.get("/documents/{doc_id}")
        def route(doc_id: int, request: Request, _=Depends(require_policy_auto(topaz_config))):
            return {"status": "ok", "id": doc_id}

        client = TestClient(app)
        response = client.get("/documents/123")
        assert response.status_code == 200

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["policy_path"] == "testapp.GET.documents.__doc_id"

    def test_auto_resolves_nested_params(self, topaz_config, patch_client):
        """Should auto-resolve nested path parameters."""
        app = FastAPI()

        @app.put("/users/{user_id}/documents/{doc_id}")
        def route(user_id: str, doc_id: int, request: Request,
                  _=Depends(require_policy_auto(topaz_config))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.put("/users/alice/documents/42")
        assert response.status_code == 200

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["policy_path"] == "testapp.PUT.users.__user_id.documents.__doc_id"

    def test_auto_denies_when_policy_returns_false(self, topaz_config, patch_client_denied):
        """Should return 403 when policy denies."""
        app = FastAPI()

        @app.get("/documents")
        def route(request: Request, _=Depends(require_policy_auto(topaz_config))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/documents")
        assert response.status_code == 403

    def test_auto_uses_custom_decision(self, topaz_config, monkeypatch):
        """Should check custom decision name."""
        mock = Mock()
        mock.decisions = AsyncMock(return_value={"can_execute": True})
        monkeypatch.setattr(TopazConfig, "create_client", lambda self, req: mock)

        app = FastAPI()

        @app.get("/run")
        def route(request: Request, _=Depends(require_policy_auto(topaz_config, decision="can_execute"))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/run")
        assert response.status_code == 200

    def test_auto_includes_path_params_in_context(self, topaz_config, patch_client):
        """Should include path parameters in resource context."""
        app = FastAPI()

        @app.get("/docs/{doc_id}/sections/{section_id}")
        def route(doc_id: int, section_id: int, request: Request,
                  _=Depends(require_policy_auto(topaz_config))):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/docs/123/sections/456")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["doc_id"] == "123"
        assert call_kwargs["resource_context"]["section_id"] == "456"

    def test_auto_merges_static_resource_context(self, topaz_config, patch_client):
        """Should merge static resource_context."""
        app = FastAPI()

        @app.get("/test")
        def route(request: Request,
                  _=Depends(require_policy_auto(topaz_config, resource_context={"extra": "data"}))):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/test")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["extra"] == "data"

    def test_auto_calls_resource_context_provider(self, authorizer_options, identity_provider, patch_client):
        """Should call resource_context_provider and merge result."""
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            resource_context_provider=lambda req: {"from_provider": "value"},
        )

        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_auto(config))):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/test")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["from_provider"] == "value"

    def test_different_http_methods(self, topaz_config, patch_client):
        """Should auto-resolve different HTTP methods correctly."""
        app = FastAPI()

        @app.get("/items")
        def get_items(request: Request, _=Depends(require_policy_auto(topaz_config))):
            return {"status": "ok"}

        @app.post("/items")
        def create_item(request: Request, _=Depends(require_policy_auto(topaz_config))):
            return {"status": "ok"}

        @app.delete("/items/{id}")
        def delete_item(id: int, request: Request, _=Depends(require_policy_auto(topaz_config))):
            return {"status": "ok"}

        client = TestClient(app)

        client.get("/items")
        assert patch_client.decisions.call_args.kwargs["policy_path"] == "testapp.GET.items"

        client.post("/items")
        assert patch_client.decisions.call_args.kwargs["policy_path"] == "testapp.POST.items"

        client.delete("/items/99")
        assert patch_client.decisions.call_args.kwargs["policy_path"] == "testapp.DELETE.items.__id"


class TestRequirePolicyAllowed:
    """
    Explicit policy path authorization dependency.

    require_policy_allowed requires an explicit policy path and raises HTTPException(403)
    when authorization fails. Use this when you need precise control over policy paths.
    """

    def test_allows_when_policy_returns_true(self, topaz_config, patch_client):
        """Should allow access when policy returns allowed=True."""
        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(topaz_config, "testapp.GET.test"))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200

    def test_denies_when_policy_returns_false(self, topaz_config, patch_client_denied):
        """Should return 403 when policy returns allowed=False."""
        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(topaz_config, "testapp.GET.test"))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 403

    def test_uses_correct_policy_path(self, topaz_config, patch_client):
        """Should pass the correct policy_path to authorizer."""
        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(topaz_config, "custom.policy.path"))):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/test")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["policy_path"] == "custom.policy.path"

    def test_uses_custom_decision_name(self, topaz_config, monkeypatch):
        """Should check custom decision name when specified."""
        mock = Mock()
        mock.decisions = AsyncMock(return_value={"can_execute": True})
        monkeypatch.setattr(TopazConfig, "create_client", lambda self, req: mock)

        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(topaz_config, "test", decision="can_execute"))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200

    def test_includes_path_params_in_context(self, topaz_config, patch_client):
        """Should include path parameters in resource context."""
        app = FastAPI()

        @app.get("/docs/{doc_id}/sections/{section_id}")
        def route(doc_id: int, section_id: int, request: Request,
                  _=Depends(require_policy_allowed(topaz_config, "test"))):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/docs/123/sections/456")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["doc_id"] == "123"
        assert call_kwargs["resource_context"]["section_id"] == "456"

    def test_merges_static_resource_context(self, topaz_config, patch_client):
        """Should merge static resource_context parameter."""
        app = FastAPI()

        dep = require_policy_allowed(topaz_config, "test", resource_context={"extra": "data"})

        @app.get("/test")
        def route(request: Request, _=Depends(dep)):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/test")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["extra"] == "data"

    def test_calls_resource_context_provider(self, authorizer_options, identity_provider, patch_client):
        """Should call resource_context_provider and merge result."""
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            resource_context_provider=lambda req: {"from_provider": "value"},
        )

        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(config, "test"))):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/test")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["from_provider"] == "value"


class TestRequireRebacAllowed:
    """
    Relationship-based access control (ReBAC) authorization.

    require_rebac_allowed checks if a subject has a specific relation to an object
    (e.g., user "alice" has "can_read" relation to document "doc-123").
    Uses the {policy_root}.check policy path for all ReBAC checks.
    """

    def test_allows_when_check_passes(self, topaz_config, patch_client):
        """Should allow access when ReBAC check returns allowed=True."""
        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  _=Depends(require_rebac_allowed(topaz_config, "document", "can_read"))):
            return {"id": id}

        client = TestClient(app)
        response = client.get("/docs/123")
        assert response.status_code == 200

    def test_denies_when_check_fails(self, topaz_config, patch_client_denied):
        """Should return 403 when ReBAC check fails."""
        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  _=Depends(require_rebac_allowed(topaz_config, "document", "can_read"))):
            return {"id": id}

        client = TestClient(app)
        response = client.get("/docs/123")
        assert response.status_code == 403

    def test_extracts_object_id_from_path_params(self, topaz_config, patch_client):
        """Should extract object_id from path param 'id' by default."""
        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  _=Depends(require_rebac_allowed(topaz_config, "document", "can_read"))):
            return {"id": id}

        client = TestClient(app)
        client.get("/docs/456")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["object_id"] == "456"

    def test_uses_static_object_id(self, topaz_config, patch_client):
        """Should use static object_id when provided as string."""
        app = FastAPI()

        @app.get("/test")
        def route(request: Request,
                  _=Depends(require_rebac_allowed(topaz_config, "document", "can_read", object_id="static-123"))):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/test")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["object_id"] == "static-123"

    def test_uses_callable_object_id(self, topaz_config, patch_client):
        """Should call object_id function when provided as callable."""
        app = FastAPI()

        def extract_id(req: Request) -> str:
            return req.query_params.get("doc_id", "")

        @app.get("/test")
        def route(request: Request,
                  _=Depends(require_rebac_allowed(topaz_config, "document", "can_read", object_id=extract_id))):
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/test?doc_id=from-query")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["object_id"] == "from-query"

    def test_includes_object_type_in_context(self, topaz_config, patch_client):
        """Should include object_type in resource context."""
        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  _=Depends(require_rebac_allowed(topaz_config, "document", "can_read"))):
            return {"id": id}

        client = TestClient(app)
        client.get("/docs/123")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["object_type"] == "document"

    def test_includes_relation_in_context(self, topaz_config, patch_client):
        """Should include relation in resource context."""
        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  _=Depends(require_rebac_allowed(topaz_config, "document", "can_write"))):
            return {"id": id}

        client = TestClient(app)
        client.get("/docs/123")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["relation"] == "can_write"

    def test_uses_custom_subject_type(self, topaz_config, patch_client):
        """Should use custom subject_type when provided."""
        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  _=Depends(require_rebac_allowed(topaz_config, "document", "can_read", subject_type="service"))):
            return {"id": id}

        client = TestClient(app)
        client.get("/docs/123")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["subject_type"] == "service"

    def test_uses_check_policy_path(self, topaz_config, patch_client):
        """Should use {policy_root}.check as policy path."""
        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  _=Depends(require_rebac_allowed(topaz_config, "document", "can_read"))):
            return {"id": id}

        client = TestClient(app)
        client.get("/docs/123")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["policy_path"] == "testapp.check"

    def test_merges_resource_context_provider(self, authorizer_options, identity_provider, patch_client):
        """Should merge resource_context_provider with ReBAC fields."""
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            resource_context_provider=lambda req: {"tenant_id": "acme"},
        )

        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  _=Depends(require_rebac_allowed(config, "document", "can_read"))):
            return {"id": id}

        client = TestClient(app)
        client.get("/docs/123")

        call_kwargs = patch_client.decisions.call_args.kwargs
        ctx = call_kwargs["resource_context"]
        assert ctx["tenant_id"] == "acme"
        assert ctx["object_type"] == "document"


@dataclass
class FakeDocument:
    """Fake document for testing."""

    id: int
    name: str
    owner: str


class TestGetAuthorizedResource:
    """
    Fetch-then-authorize pattern for resource access.

    get_authorized_resource fetches a resource first, then checks authorization.
    Returns 404 if resource not found, 403 if not authorized, or the resource if allowed.
    """

    def test_returns_resource_when_authorized(self, topaz_config, patch_client):
        """Should return fetched resource when authorization passes."""
        fake_doc = FakeDocument(id=123, name="Test", owner="alice")

        def fetcher(req, db):
            return fake_doc

        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  doc=Depends(get_authorized_resource(topaz_config, fetcher, "document", "can_read"))):
            return {"name": doc.name}

        client = TestClient(app)
        response = client.get("/docs/123")
        assert response.status_code == 200
        assert response.json()["name"] == "Test"

    def test_returns_404_when_resource_not_found(self, topaz_config, patch_client):
        """Should return 404 when resource_fetcher returns None."""
        def fetcher(req, db):
            return None

        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  doc=Depends(get_authorized_resource(topaz_config, fetcher, "document", "can_read"))):
            return {"name": doc.name}

        client = TestClient(app)
        response = client.get("/docs/123")
        assert response.status_code == 404

    def test_returns_403_when_not_authorized(self, topaz_config, patch_client_denied):
        """Should return 403 when resource found but not authorized."""
        fake_doc = FakeDocument(id=123, name="Test", owner="alice")

        def fetcher(req, db):
            return fake_doc

        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  doc=Depends(get_authorized_resource(topaz_config, fetcher, "document", "can_read"))):
            return {"name": doc.name}

        client = TestClient(app)
        response = client.get("/docs/123")
        assert response.status_code == 403

    def test_uses_object_id_from_path_params(self, topaz_config, patch_client):
        """Should use path param 'id' as object_id by default."""
        fake_doc = FakeDocument(id=456, name="Test", owner="alice")

        def fetcher(req, db):
            return fake_doc

        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request,
                  doc=Depends(get_authorized_resource(topaz_config, fetcher, "document", "can_read"))):
            return {"id": doc.id}

        client = TestClient(app)
        client.get("/docs/456")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["object_id"] == "456"

    def test_uses_static_object_id(self, topaz_config, patch_client):
        """Should use static object_id when provided."""
        fake_doc = FakeDocument(id=123, name="Test", owner="alice")

        def fetcher(req, db):
            return fake_doc

        dep = get_authorized_resource(topaz_config, fetcher, "document", "can_read", object_id="fixed-id")

        app = FastAPI()

        @app.get("/docs/{id}")
        def route(id: int, request: Request, doc=Depends(dep)):
            return {"id": doc.id}

        client = TestClient(app)
        client.get("/docs/123")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["object_id"] == "fixed-id"


class TestFilterAuthorizedResources:
    """
    Batch authorization filtering for resource lists.

    filter_authorized_resources checks authorization for each resource in a list
    and returns only those the user is authorized to access. Checks run concurrently
    for performance.
    """

    def test_returns_empty_for_empty_list(self, topaz_config, patch_client):
        """Should return empty list when given empty list."""
        app = FastAPI()

        @app.get("/documents")
        async def route(request: Request,
                        filter_fn=Depends(filter_authorized_resources(topaz_config, "document", "can_read"))):
            return {"result": await filter_fn([])}

        client = TestClient(app)
        response = client.get("/documents")
        assert response.json()["result"] == []

    def test_keeps_authorized_resources(self, topaz_config, patch_client):
        """Should keep resources that pass authorization."""
        documents = [
            FakeDocument(id=1, name="Doc1", owner="alice"),
            FakeDocument(id=2, name="Doc2", owner="bob"),
        ]

        app = FastAPI()

        @app.get("/documents")
        async def route(request: Request,
                        filter_fn=Depends(filter_authorized_resources(topaz_config, "document", "can_read"))):
            result = await filter_fn(documents)
            return {"count": len(result), "ids": [d.id for d in result]}

        client = TestClient(app)
        response = client.get("/documents")
        assert response.json()["count"] == 2
        assert response.json()["ids"] == [1, 2]

    def test_filters_unauthorized_resources(self, topaz_config, monkeypatch):
        """Should filter out resources that fail authorization."""
        call_count = [0]

        def mock_create_client(self, req):
            mock = Mock()

            async def decisions_side_effect(**kwargs):
                call_count[0] += 1
                obj_id = kwargs["resource_context"]["object_id"]
                return {"allowed": obj_id == "1"}  # Only allow id=1

            mock.decisions = decisions_side_effect
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        documents = [
            FakeDocument(id=1, name="Allowed", owner="alice"),
            FakeDocument(id=2, name="Denied", owner="bob"),
            FakeDocument(id=3, name="Denied", owner="charlie"),
        ]

        app = FastAPI()

        @app.get("/documents")
        async def route(request: Request,
                        filter_fn=Depends(filter_authorized_resources(topaz_config, "document", "can_read"))):
            result = await filter_fn(documents)
            return {"ids": [d.id for d in result]}

        client = TestClient(app)
        response = client.get("/documents")
        assert response.json()["ids"] == [1]

    def test_uses_custom_id_extractor(self, topaz_config, patch_client):
        """Should use custom id_extractor function."""
        @dataclass
        class CustomDoc:
            doc_id: str
            title: str

        documents = [CustomDoc(doc_id="abc", title="Doc1")]

        app = FastAPI()

        dep = filter_authorized_resources(
            topaz_config, "document", "can_read",
            id_extractor=lambda d: d.doc_id
        )

        @app.get("/documents")
        async def route(request: Request, filter_fn=Depends(dep)):
            result = await filter_fn(documents)
            return {"count": len(result)}

        client = TestClient(app)
        client.get("/documents")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["object_id"] == "abc"

    def test_uses_custom_subject_type(self, topaz_config, patch_client):
        """Should use custom subject_type."""
        documents = [FakeDocument(id=1, name="Doc1", owner="alice")]

        app = FastAPI()

        dep = filter_authorized_resources(
            topaz_config, "document", "can_read",
            subject_type="group"
        )

        @app.get("/documents")
        async def route(request: Request, filter_fn=Depends(dep)):
            await filter_fn(documents)
            return {"status": "ok"}

        client = TestClient(app)
        client.get("/documents")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["subject_type"] == "group"


@pytest.mark.asyncio
class TestAsyncRoutes:
    """
    Async route compatibility verification.

    All authorization dependencies must work correctly with both sync and async
    FastAPI routes. These tests verify proper async behavior using AsyncClient.
    """

    @pytest.fixture
    def async_app(self, topaz_config):
        """Create a FastAPI app with async routes."""
        app = FastAPI()

        @app.get("/policy-check")
        async def policy_route(
            request: Request,
            _: None = Depends(require_policy_allowed(topaz_config, "testapp.GET.policy")),
        ):
            return {"status": "ok", "route": "policy"}

        @app.get("/rebac-check/{id}")
        async def rebac_route(
            id: int,
            request: Request,
            _: None = Depends(require_rebac_allowed(topaz_config, "document", "can_read")),
        ):
            return {"status": "ok", "id": id}

        @app.get("/fetch-resource/{id}")
        async def fetch_route(
            id: int,
            request: Request,
            doc: FakeDocument = Depends(
                get_authorized_resource(
                    topaz_config,
                    lambda req, db: FakeDocument(
                        id=int(req.path_params["id"]),
                        name="Async Doc",
                        owner="alice",
                    ),
                    "document",
                    "can_read",
                )
            ),
        ):
            return {"status": "ok", "name": doc.name}

        @app.get("/filter-resources")
        async def filter_route(
            request: Request,
            filter_fn=Depends(filter_authorized_resources(topaz_config, "document", "can_read")),
        ):
            documents = [
                FakeDocument(id=1, name="Doc1", owner="alice"),
                FakeDocument(id=2, name="Doc2", owner="bob"),
            ]
            authorized = await filter_fn(documents)
            return {"status": "ok", "count": len(authorized)}

        return app

    async def test_async_policy_allowed(self, async_app, patch_client):
        """Async route with require_policy_allowed should work correctly."""
        async with AsyncClient(
            transport=ASGITransport(app=async_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/policy-check")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "route": "policy"}

    async def test_async_policy_denied(self, async_app, patch_client_denied):
        """Async route should return 403 when policy denies."""
        async with AsyncClient(
            transport=ASGITransport(app=async_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/policy-check")

        assert response.status_code == 403

    async def test_async_rebac_allowed(self, async_app, patch_client):
        """Async route with require_rebac_allowed should work correctly."""
        async with AsyncClient(
            transport=ASGITransport(app=async_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/rebac-check/123")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "id": 123}

    async def test_async_rebac_denied(self, async_app, patch_client_denied):
        """Async route should return 403 when ReBAC check fails."""
        async with AsyncClient(
            transport=ASGITransport(app=async_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/rebac-check/123")

        assert response.status_code == 403

    async def test_async_get_authorized_resource(self, async_app, patch_client):
        """Async route with get_authorized_resource should return fetched resource."""
        async with AsyncClient(
            transport=ASGITransport(app=async_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/fetch-resource/456")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "name": "Async Doc"}

    async def test_async_get_authorized_resource_denied(self, async_app, patch_client_denied):
        """Async route should return 403 when resource access denied."""
        async with AsyncClient(
            transport=ASGITransport(app=async_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/fetch-resource/456")

        assert response.status_code == 403

    async def test_async_filter_resources(self, async_app, patch_client):
        """Async route with filter_authorized_resources should filter correctly."""
        async with AsyncClient(
            transport=ASGITransport(app=async_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/filter-resources")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "count": 2}

    async def test_async_filter_partial_authorization(self, async_app, monkeypatch):
        """Async route should filter based on per-resource authorization."""
        def mock_create_client(self, req):
            mock = Mock()

            async def decisions_side_effect(**kwargs):
                obj_id = kwargs["resource_context"]["object_id"]
                return {"allowed": obj_id == "1"}  # Only allow id=1

            mock.decisions = decisions_side_effect
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        async with AsyncClient(
            transport=ASGITransport(app=async_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/filter-resources")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "count": 1}


@pytest.mark.asyncio
class TestDecisionCache:
    """
    TTL-based authorization decision caching.

    DecisionCache stores authorization decisions with time-based expiration to reduce
    calls to the authorizer. Cache keys include identity, policy path, decision name,
    and resource context to ensure correct cache isolation.
    """

    async def test_cache_miss_returns_none(self):
        """Cache should return None for uncached entries."""
        cache = DecisionCache(ttl_seconds=60)
        result = await cache.get("user-1", "policy.path", "allowed", {"key": "value"})
        assert result is None

    async def test_cache_hit_returns_value(self):
        """Cache should return cached value."""
        cache = DecisionCache(ttl_seconds=60)
        await cache.set("user-1", "policy.path", "allowed", {"key": "value"}, True)
        result = await cache.get("user-1", "policy.path", "allowed", {"key": "value"})
        assert result is True

    async def test_cache_stores_false_values(self):
        """Cache should correctly store and return False values."""
        cache = DecisionCache(ttl_seconds=60)
        await cache.set("user-1", "policy.path", "allowed", None, False)
        result = await cache.get("user-1", "policy.path", "allowed", None)
        assert result is False

    async def test_cache_key_includes_all_params(self):
        """Different parameters should create different cache keys."""
        cache = DecisionCache(ttl_seconds=60)

        # Set value for user-1
        await cache.set("user-1", "policy.path", "allowed", None, True)

        # Different user should miss
        result = await cache.get("user-2", "policy.path", "allowed", None)
        assert result is None

        # Different policy should miss
        result = await cache.get("user-1", "other.path", "allowed", None)
        assert result is None

        # Different decision should miss
        result = await cache.get("user-1", "policy.path", "denied", None)
        assert result is None

        # Different context should miss
        result = await cache.get("user-1", "policy.path", "allowed", {"extra": "data"})
        assert result is None

        # Original should still hit
        result = await cache.get("user-1", "policy.path", "allowed", None)
        assert result is True

    async def test_cache_expiration(self, monkeypatch):
        """Cache entries should expire after TTL."""

        current_time = [1000.0]

        def mock_monotonic():
            return current_time[0]

        # Monkeypatch time.monotonic in the dependencies module
        import fastapi_topaz.dependencies as deps
        monkeypatch.setattr(deps.time, "monotonic", mock_monotonic)

        cache = DecisionCache(ttl_seconds=60)
        await cache.set("user-1", "policy.path", "allowed", None, True)

        # Should hit before expiration
        result = await cache.get("user-1", "policy.path", "allowed", None)
        assert result is True

        # Advance time past TTL
        current_time[0] = 1061.0

        # Should miss after expiration
        result = await cache.get("user-1", "policy.path", "allowed", None)
        assert result is None

    async def test_cache_max_size_eviction(self):
        """Cache should evict entries when max_size is reached."""
        cache = DecisionCache(ttl_seconds=60, max_size=10)

        # Fill cache to max
        for i in range(10):
            await cache.set(f"user-{i}", "policy.path", "allowed", None, True)

        # Verify all entries exist
        for i in range(10):
            result = await cache.get(f"user-{i}", "policy.path", "allowed", None)
            assert result is True

        # Add one more entry, should trigger eviction
        await cache.set("user-new", "policy.path", "allowed", None, True)

        # New entry should exist
        result = await cache.get("user-new", "policy.path", "allowed", None)
        assert result is True

    async def test_cache_clear(self):
        """Cache clear should remove all entries."""
        cache = DecisionCache(ttl_seconds=60)

        await cache.set("user-1", "policy.path", "allowed", None, True)
        await cache.set("user-2", "policy.path", "allowed", None, True)

        await cache.clear()

        result = await cache.get("user-1", "policy.path", "allowed", None)
        assert result is None
        result = await cache.get("user-2", "policy.path", "allowed", None)
        assert result is None


@pytest.mark.asyncio
class TestTopazConfigWithCache:
    """
    TopazConfig integration with decision caching.

    When decision_cache is configured, TopazConfig automatically caches authorization
    results to reduce authorizer calls for repeated checks with the same parameters.
    """

    @pytest.fixture
    def cached_config(self, authorizer_options, identity_provider):
        """Create a TopazConfig with caching enabled."""
        cache = DecisionCache(ttl_seconds=60)
        return TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test-policy",
            decision_cache=cache,
        )

    async def test_cache_reduces_client_calls(self, cached_config, monkeypatch):
        """With caching enabled, repeated checks should use cache."""
        call_count = [0]

        def mock_create_client(self, req):
            call_count[0] += 1
            mock = Mock()
            mock.decisions = AsyncMock(return_value={"allowed": True})
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        app = FastAPI()

        @app.get("/test")
        async def route(
            request: Request,
            _=Depends(require_policy_allowed(cached_config, "testapp.GET.test")),
        ):
            return {"status": "ok"}

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # First request - should call authorizer
            await client.get("/test")
            assert call_count[0] == 1

            # Second request - should use cache
            await client.get("/test")
            assert call_count[0] == 1  # No additional call

            # Third request - should still use cache
            await client.get("/test")
            assert call_count[0] == 1  # No additional call

    async def test_different_requests_not_cached(self, cached_config, monkeypatch):
        """Different authorization contexts should not share cache."""
        call_count = [0]

        def mock_create_client(self, req):
            call_count[0] += 1
            mock = Mock()
            mock.decisions = AsyncMock(return_value={"allowed": True})
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        app = FastAPI()

        @app.get("/docs/{id}")
        async def route(
            id: int,
            request: Request,
            _=Depends(require_rebac_allowed(cached_config, "document", "can_read")),
        ):
            return {"id": id}

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Different IDs should not share cache
            await client.get("/docs/1")
            assert call_count[0] == 1

            await client.get("/docs/2")
            assert call_count[0] == 2

            # Same ID should use cache
            await client.get("/docs/1")
            assert call_count[0] == 2


@pytest.mark.asyncio
class TestConcurrentFilter:
    """
    Concurrent authorization check performance.

    filter_authorized_resources runs checks concurrently for better performance.
    max_concurrent_checks limits parallelism to avoid overwhelming the authorizer.
    """

    async def test_concurrent_checks_are_faster(self, topaz_config, monkeypatch):
        """Concurrent checks should complete faster than sequential."""
        import time

        delay = 0.05  # 50ms delay per check

        async def slow_decisions(**kwargs):
            await asyncio.sleep(delay)
            return {"allowed": True}

        def mock_create_client(self, req):
            mock = Mock()
            mock.decisions = slow_decisions
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        app = FastAPI()

        @app.get("/documents")
        async def route(
            request: Request,
            filter_fn=Depends(filter_authorized_resources(topaz_config, "document", "can_read")),
        ):
            documents = [FakeDocument(id=i, name=f"Doc{i}", owner="alice") for i in range(10)]
            start = time.monotonic()
            result = await filter_fn(documents)
            elapsed = time.monotonic() - start
            return {"count": len(result), "elapsed": elapsed}

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/documents")

        data = response.json()
        assert data["count"] == 10

        # With concurrent execution, 10 checks with 50ms each should complete
        # much faster than 500ms (sequential would be ~500ms)
        # Allow some overhead, but should be significantly less than sequential
        assert data["elapsed"] < 0.3  # Should be ~50-100ms with concurrency

    async def test_semaphore_limits_concurrency(self, authorizer_options, identity_provider, monkeypatch):
        """Semaphore should limit concurrent authorization checks."""
        max_concurrent = [0]
        current_concurrent = [0]

        async def tracking_decisions(**kwargs):
            current_concurrent[0] += 1
            max_concurrent[0] = max(max_concurrent[0], current_concurrent[0])
            await asyncio.sleep(0.02)
            current_concurrent[0] -= 1
            return {"allowed": True}

        def mock_create_client(self, req):
            mock = Mock()
            mock.decisions = tracking_decisions
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        # Config with max 3 concurrent checks
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test-policy",
            max_concurrent_checks=3,
        )

        app = FastAPI()

        @app.get("/documents")
        async def route(
            request: Request,
            filter_fn=Depends(filter_authorized_resources(config, "document", "can_read")),
        ):
            documents = [FakeDocument(id=i, name=f"Doc{i}", owner="alice") for i in range(20)]
            result = await filter_fn(documents)
            return {"count": len(result), "max_concurrent": max_concurrent[0]}

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/documents")

        data = response.json()
        assert data["count"] == 20
        # Max concurrent should be limited to 3
        assert data["max_concurrent"] <= 3


@pytest.mark.asyncio
class TestIsAllowed:
    """
    Non-raising permission checks with is_allowed().

    Unlike require_* dependencies that raise HTTPException on denial, is_allowed()
    returns a boolean. Use this when you need to check permissions without blocking
    (e.g., to conditionally show UI elements).
    """

    async def test_returns_true_when_allowed(self, topaz_config, patch_client):
        """is_allowed should return True when policy allows."""
        app = FastAPI()

        @app.get("/docs/{id}")
        async def route(id: int, request: Request):
            can_edit = await topaz_config.is_allowed(
                request,
                policy_path="testapp.PUT.documents",
                resource_context={"id": str(id)},
            )
            return {"can_edit": can_edit}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/docs/123")

        assert response.status_code == 200
        assert response.json()["can_edit"] is True

    async def test_returns_false_when_denied(self, topaz_config, patch_client_denied):
        """is_allowed should return False when policy denies (no exception)."""
        app = FastAPI()

        @app.get("/docs/{id}")
        async def route(id: int, request: Request):
            can_edit = await topaz_config.is_allowed(
                request, policy_path="testapp.PUT.documents"
            )
            return {"can_edit": can_edit}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/docs/123")

        assert response.status_code == 200  # No 403!
        assert response.json()["can_edit"] is False

    async def test_merges_resource_context(self, topaz_config, patch_client):
        """is_allowed should merge static context with path params."""
        app = FastAPI()

        @app.get("/docs/{doc_id}")
        async def route(doc_id: int, request: Request):
            await topaz_config.is_allowed(
                request,
                policy_path="testapp.GET.documents",
                resource_context={"extra": "data"},
            )
            return {"status": "ok"}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.get("/docs/456")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["resource_context"]["extra"] == "data"
        assert call_kwargs["resource_context"]["doc_id"] == "456"


@pytest.mark.asyncio
class TestCheckRelation:
    """
    Non-raising ReBAC relation check with check_relation().

    Returns boolean instead of raising HTTPException. Use when you need to check
    a single relation without blocking the request.
    """

    async def test_returns_true_when_relation_exists(self, topaz_config, patch_client):
        """check_relation should return True when relation exists."""
        app = FastAPI()

        @app.get("/docs/{id}")
        async def route(id: int, request: Request):
            can_delete = await topaz_config.check_relation(
                request, object_type="document", object_id=str(id), relation="can_delete"
            )
            return {"can_delete": can_delete}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/docs/123")

        assert response.json()["can_delete"] is True

    async def test_returns_false_when_relation_missing(self, topaz_config, patch_client_denied):
        """check_relation should return False (no exception) when denied."""
        app = FastAPI()

        @app.get("/docs/{id}")
        async def route(id: int, request: Request):
            can_delete = await topaz_config.check_relation(
                request, object_type="document", object_id=str(id), relation="can_delete"
            )
            return {"can_delete": can_delete}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/docs/123")

        assert response.status_code == 200  # No 403!
        assert response.json()["can_delete"] is False

    async def test_uses_check_policy_path(self, topaz_config, patch_client):
        """check_relation should use {root}.check policy path."""
        app = FastAPI()

        @app.get("/test")
        async def route(request: Request):
            await topaz_config.check_relation(
                request, object_type="document", object_id="123", relation="can_read"
            )
            return {"status": "ok"}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.get("/test")

        call_kwargs = patch_client.decisions.call_args.kwargs
        assert call_kwargs["policy_path"] == "testapp.check"
        assert call_kwargs["resource_context"]["object_type"] == "document"
        assert call_kwargs["resource_context"]["relation"] == "can_read"


@pytest.mark.asyncio
class TestCheckRelations:
    """
    Batch permission checks with check_relations().

    Checks multiple relations for a single object concurrently and returns a dict
    mapping relation names to boolean results. Useful for building permission UIs.
    """

    async def test_returns_dict_of_permissions(self, topaz_config, monkeypatch):
        """check_relations should return dict mapping relations to booleans."""
        def mock_create_client(self, req):
            mock = Mock()
            async def decisions_side_effect(**kwargs):
                rel = kwargs["resource_context"]["relation"]
                return {"allowed": rel in ["can_read", "can_write"]}
            mock.decisions = decisions_side_effect
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        app = FastAPI()

        @app.get("/docs/{id}")
        async def route(id: int, request: Request):
            perms = await topaz_config.check_relations(
                request,
                object_type="document",
                object_id=str(id),
                relations=["can_read", "can_write", "can_delete"],
            )
            return {"permissions": perms}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/docs/123")

        perms = response.json()["permissions"]
        assert perms == {"can_read": True, "can_write": True, "can_delete": False}

    async def test_checks_run_concurrently(self, topaz_config, monkeypatch):
        """check_relations should run checks concurrently."""
        max_concurrent = [0]
        current = [0]

        async def tracking_decisions(**kwargs):
            current[0] += 1
            max_concurrent[0] = max(max_concurrent[0], current[0])
            await asyncio.sleep(0.01)
            current[0] -= 1
            return {"allowed": True}

        def mock_create_client(self, req):
            mock = Mock()
            mock.decisions = tracking_decisions
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        app = FastAPI()

        @app.get("/test")
        async def route(request: Request):
            await topaz_config.check_relations(
                request,
                object_type="doc",
                object_id="1",
                relations=["r1", "r2", "r3", "r4", "r5"],
            )
            return {"max_concurrent": max_concurrent[0]}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        # Should have some concurrency (more than 1)
        assert response.json()["max_concurrent"] > 1


@pytest.mark.asyncio
class TestCheckHierarchy:
    """Tests for TopazConfig.check_hierarchy() non-raising method."""

    async def test_mode_all_passes_when_all_allowed(self, topaz_config, patch_client):
        """Mode 'all' should return allowed=True when all checks pass."""
        app = FastAPI()

        @app.get("/orgs/{org_id}/docs/{doc_id}")
        async def route(org_id: str, doc_id: str, request: Request):
            result = await topaz_config.check_hierarchy(
                request,
                checks=[("organization", "org_id", "member"), ("document", "doc_id", "can_read")],
            )
            return {"allowed": result.allowed, "checks": len(result.checks)}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/orgs/org-1/docs/doc-1")

        assert response.json()["allowed"] is True
        assert response.json()["checks"] == 2

    async def test_mode_all_fails_with_denied_at(self, topaz_config, monkeypatch):
        """Mode 'all' should return denied_at when a check fails."""
        def mock_create_client(self, req):
            mock = Mock()
            async def decisions_side_effect(**kwargs):
                obj_type = kwargs["resource_context"]["object_type"]
                return {"allowed": obj_type != "project"}
            mock.decisions = decisions_side_effect
            return mock
        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        app = FastAPI()

        @app.get("/orgs/{org_id}/projects/{proj_id}")
        async def route(org_id: str, proj_id: str, request: Request):
            result = await topaz_config.check_hierarchy(
                request,
                checks=[("organization", "org_id", "member"), ("project", "proj_id", "viewer")],
            )
            return {"allowed": result.allowed, "denied_at": result.denied_at}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/orgs/org-1/projects/proj-1")

        assert response.json()["allowed"] is False
        assert response.json()["denied_at"] == "project"

    async def test_mode_any_passes_when_one_allowed(self, topaz_config, monkeypatch):
        """Mode 'any' should return allowed=True when at least one check passes."""
        def mock_create_client(self, req):
            mock = Mock()
            async def decisions_side_effect(**kwargs):
                rel = kwargs["resource_context"]["relation"]
                return {"allowed": rel == "viewer"}
            mock.decisions = decisions_side_effect
            return mock
        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        app = FastAPI()

        @app.get("/docs/{doc_id}")
        async def route(doc_id: str, request: Request):
            result = await topaz_config.check_hierarchy(
                request,
                checks=[("document", "doc_id", "owner"), ("document", "doc_id", "viewer")],
                mode="any",
            )
            return {"allowed": result.allowed}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/docs/doc-1")

        assert response.json()["allowed"] is True

    async def test_mode_first_match_returns_relation(self, topaz_config, monkeypatch):
        """Mode 'first_match' should return the first matching relation."""
        def mock_create_client(self, req):
            mock = Mock()
            async def decisions_side_effect(**kwargs):
                rel = kwargs["resource_context"]["relation"]
                return {"allowed": rel == "editor"}
            mock.decisions = decisions_side_effect
            return mock
        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        app = FastAPI()

        @app.get("/docs/{doc_id}")
        async def route(doc_id: str, request: Request):
            result = await topaz_config.check_hierarchy(
                request,
                checks=[("document", "doc_id", "owner"), ("document", "doc_id", "editor"), ("document", "doc_id", "viewer")],
                mode="first_match",
            )
            return {"allowed": result.allowed, "first_match": result.first_match}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/docs/doc-1")

        assert response.json()["allowed"] is True
        assert response.json()["first_match"] == "editor"


@pytest.mark.asyncio
class TestRequireRebacHierarchy:
    """Tests for require_rebac_hierarchy dependency."""

    async def test_allows_when_all_checks_pass(self, topaz_config, patch_client):
        """Should allow access when all hierarchy checks pass."""
        app = FastAPI()

        @app.get("/orgs/{org_id}/docs/{doc_id}")
        async def route(
            org_id: str, doc_id: str, request: Request,
            _=Depends(require_rebac_hierarchy(topaz_config, [
                ("organization", "org_id", "member"),
                ("document", "doc_id", "can_read"),
            ])),
        ):
            return {"status": "ok"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/orgs/org-1/docs/doc-1")

        assert response.status_code == 200

    async def test_denies_with_403_when_check_fails(self, topaz_config, monkeypatch):
        """Should return 403 when a hierarchy check fails."""
        def mock_create_client(self, req):
            mock = Mock()
            async def decisions_side_effect(**kwargs):
                return {"allowed": kwargs["resource_context"]["object_type"] == "organization"}
            mock.decisions = decisions_side_effect
            return mock
        monkeypatch.setattr(TopazConfig, "create_client", mock_create_client)

        app = FastAPI()

        @app.get("/orgs/{org_id}/docs/{doc_id}")
        async def route(
            org_id: str, doc_id: str, request: Request,
            _=Depends(require_rebac_hierarchy(topaz_config, [
                ("organization", "org_id", "member"),
                ("document", "doc_id", "can_read"),
            ])),
        ):
            return {"status": "ok"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/orgs/org-1/docs/doc-1")

        assert response.status_code == 403
        assert "document" in response.json()["detail"]

"""
Tests for audit logging.

The audit module provides structured logging for authorization decisions.
AuditEvent captures decision context (identity, resource, result) and
AuditLogger handles event emission with configurable filtering.

Test organization:
- TestAuditEvent: Event data structure and serialization
- TestAuditLogger: Logging behavior, filtering, and handlers
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from fastapi_topaz.audit import AuditEvent, AuditLogger


class TestAuditEvent:
    """
    AuditEvent data structure and serialization.

    AuditEvent captures authorization decision context and can be serialized
    to dict or JSON for logging backends.
    """

    def test_to_dict_basic(self):
        event = AuditEvent(
            event="authorization.dependency.allowed",
            source="dependency",
            policy_path="myapp.GET.documents",
            decision="allowed",
        )
        data = event.to_dict()
        assert data["event"] == "authorization.dependency.allowed"
        assert data["source"] == "dependency"
        assert data["authorization"]["policy_path"] == "myapp.GET.documents"
        assert data["authorization"]["decision"] == "allowed"

    def test_to_dict_with_identity(self):
        event = AuditEvent(
            event="test",
            identity_type="sub",
            identity_value="user-123",
        )
        data = event.to_dict()
        assert data["identity"]["type"] == "sub"
        assert data["identity"]["value"] == "user-123"

    def test_to_dict_with_rebac(self):
        event = AuditEvent(
            event="authorization.dependency.allowed",
            check_type="rebac",
            object_type="document",
            object_id="doc-123",
            relation="can_write",
        )
        data = event.to_dict()
        assert data["authorization"]["check_type"] == "rebac"
        assert data["resource"]["object_type"] == "document"
        assert data["resource"]["object_id"] == "doc-123"
        assert data["resource"]["relation"] == "can_write"

    def test_to_dict_with_request(self):
        event = AuditEvent(
            event="test",
            method="GET",
            path="/documents/123",
            client_ip="192.168.1.1",
        )
        data = event.to_dict()
        assert data["request"]["method"] == "GET"
        assert data["request"]["path"] == "/documents/123"
        assert data["request"]["ip"] == "192.168.1.1"

    def test_to_json(self):
        event = AuditEvent(event="test", source="dependency")
        json_str = event.to_json()
        data = json.loads(json_str)
        assert data["event"] == "test"


class TestAuditLogger:
    """
    AuditLogger event emission and filtering.

    Configurable options:
    - log_allowed/log_denied: Filter by decision result
    - log_manual_checks: Include batch check logs
    - handler: Sync or async function to receive events
    """

    @pytest.mark.asyncio
    async def test_log_decision_allowed(self):
        events = []

        async def capture(e):
            events.append(e)

        logger = AuditLogger(handler=capture)
        await logger.log_decision(None, "myapp.GET.test", True)

        assert len(events) == 1
        assert events[0].decision == "allowed"
        assert "allowed" in events[0].event

    @pytest.mark.asyncio
    async def test_log_decision_denied(self):
        events = []

        async def capture(e):
            events.append(e)

        logger = AuditLogger(handler=capture)
        await logger.log_decision(None, "myapp.GET.test", False)

        assert len(events) == 1
        assert events[0].decision == "denied"
        assert events[0].level == "WARNING"

    @pytest.mark.asyncio
    async def test_log_allowed_disabled(self):
        events = []

        async def capture(e):
            events.append(e)

        logger = AuditLogger(handler=capture, log_allowed=False)
        await logger.log_decision(None, "myapp.GET.test", True)

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_log_denied_disabled(self):
        events = []

        async def capture(e):
            events.append(e)

        logger = AuditLogger(handler=capture, log_denied=False)
        await logger.log_decision(None, "myapp.GET.test", False)

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_log_with_request(self):
        events = []

        async def capture(e):
            events.append(e)

        request = Mock()
        request.method = "POST"
        request.url = Mock()
        request.url.path = "/documents"
        request.headers = {}
        request.client = Mock()
        request.client.host = "10.0.0.1"
        request.state = Mock(spec=[])

        logger = AuditLogger(handler=capture)
        await logger.log_decision(request, "myapp.POST.documents", True)

        assert events[0].method == "POST"
        assert events[0].path == "/documents"
        assert events[0].client_ip == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_log_batch_check(self):
        events = []

        async def capture(e):
            events.append(e)

        logger = AuditLogger(handler=capture, log_manual_checks=True)
        await logger.log_batch_check(
            None,
            object_type="document",
            object_id="doc-123",
            results={"can_read": True, "can_write": False},
        )

        assert len(events) == 1
        assert events[0].results == {"can_read": True, "can_write": False}
        assert events[0].check_type == "rebac_batch"

    @pytest.mark.asyncio
    async def test_log_batch_check_disabled(self):
        events = []

        async def capture(e):
            events.append(e)

        logger = AuditLogger(handler=capture, log_manual_checks=False)
        await logger.log_batch_check(None, "document", "doc-123", {"can_read": True})

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_log_unauthenticated_event(self):
        events = []

        async def capture(e):
            events.append(e)

        logger = AuditLogger(handler=capture)
        await logger.log_unauthenticated_event(request=None, reason="missing_token")

        assert len(events) == 1
        assert events[0].event == "authorization.middleware.unauthenticated"
        assert events[0].reason == "missing_token"
        assert events[0].level == "WARNING"

    @pytest.mark.asyncio
    async def test_request_id_from_header(self):
        events = []

        async def capture(e):
            events.append(e)

        request = Mock()
        request.method = "GET"
        request.url = Mock()
        request.url.path = "/test"
        request.headers = {"x-request-id": "req-abc123"}
        request.client = None

        logger = AuditLogger(handler=capture)
        await logger.log_decision(request, "test", True)

        assert events[0].request_id == "req-abc123"

    @pytest.mark.asyncio
    async def test_sync_handler(self):
        """Test that sync handlers work too."""
        events = []

        def capture(e):
            events.append(e)

        logger = AuditLogger(handler=capture)
        await logger.log_decision(None, "test", True)

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_manual_source_gated_by_log_manual_checks(self):
        """source='manual' events are dropped unless log_manual_checks is set."""
        events = []

        def capture(e):
            events.append(e)

        logger = AuditLogger(handler=capture, log_manual_checks=False)
        await logger.log_decision(None, "test", True, source="manual")
        assert len(events) == 0

        logger = AuditLogger(handler=capture, log_manual_checks=True)
        await logger.log_decision(None, "test", True, source="manual")
        assert len(events) == 1
        assert events[0].source == "manual"


class TestAuditFromCheckDecision:
    """D4: check_decision emits audit events for every caller, not just middleware."""

    def _make_config(self, audit_logger, monkeypatch):
        from unittest.mock import AsyncMock

        from aserto.client import AuthorizerOptions, Identity, IdentityType

        from fastapi_topaz import TopazConfig
        from fastapi_topaz._client import SharedAuthorizerClient

        monkeypatch.setattr(
            SharedAuthorizerClient, "decisions", AsyncMock(return_value={"allowed": True})
        )
        return TopazConfig(
            authorizer_options=AuthorizerOptions(url="localhost:8282"),
            policy_path_root="testapp",
            identity_provider=lambda r: Identity(
                type=IdentityType.IDENTITY_TYPE_SUB, value="user-1"
            ),
            policy_instance_name="test",
            audit_logger=audit_logger,
        )

    def _make_request(self):
        from fastapi import Request

        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/docs/1",
                "path_params": {},
                "headers": [],
                "query_string": b"",
            }
        )

    @pytest.mark.asyncio
    async def test_dependency_source_emits_event(self, monkeypatch):
        events = []
        config = self._make_config(AuditLogger(handler=events.append), monkeypatch)

        await config.check_decision(self._make_request(), "testapp.GET.docs", "allowed")

        assert len(events) == 1
        assert events[0].source == "dependency"
        assert events[0].decision == "allowed"
        assert events[0].identity_value == "user-1"

    @pytest.mark.asyncio
    async def test_is_allowed_silent_by_default(self, monkeypatch):
        events = []
        config = self._make_config(AuditLogger(handler=events.append), monkeypatch)

        await config.is_allowed(self._make_request(), "testapp.GET.docs")

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_is_allowed_emits_manual_with_log_manual_checks(self, monkeypatch):
        events = []
        config = self._make_config(
            AuditLogger(handler=events.append, log_manual_checks=True), monkeypatch
        )

        await config.is_allowed(self._make_request(), "testapp.GET.docs")

        assert len(events) == 1
        assert events[0].source == "manual"

    @pytest.mark.asyncio
    async def test_rebac_event_carries_object_fields(self, monkeypatch):
        events = []
        config = self._make_config(
            AuditLogger(handler=events.append, log_manual_checks=True), monkeypatch
        )

        await config.check_relation(
            self._make_request(), object_type="document", object_id="doc-1", relation="can_read"
        )

        assert len(events) == 1
        assert events[0].check_type == "rebac"
        assert events[0].object_type == "document"
        assert events[0].object_id == "doc-1"
        assert events[0].relation == "can_read"


class TestD5AuditKnobs:
    """D5: log_skipped and include_request_headers are functional."""

    @pytest.mark.asyncio
    async def test_log_skipped_event(self):
        events = []
        logger = AuditLogger(handler=events.append, log_skipped=True)
        await logger.log_skipped_event(None, "excluded")
        assert len(events) == 1
        assert events[0].event == "authorization.middleware.skipped"
        assert events[0].reason == "excluded"

    @pytest.mark.asyncio
    async def test_log_skipped_disabled_by_default(self):
        events = []
        logger = AuditLogger(handler=events.append)
        await logger.log_skipped_event(None, "excluded")
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_include_request_headers_redacts_credentials(self):
        events = []
        request = Mock()
        request.method = "GET"
        request.url = Mock()
        request.url.path = "/test"
        request.headers = {
            "authorization": "Bearer secret",
            "cookie": "session=abc",
            "x-tenant": "acme",
            "x-request-id": "req-1",
        }
        request.client = None

        logger = AuditLogger(handler=events.append, include_request_headers=True)
        await logger.log_decision(request, "test", True)

        headers = events[0].to_dict()["request"]["headers"]
        assert headers["authorization"] == "[REDACTED]"
        assert headers["cookie"] == "[REDACTED]"
        assert headers["x-tenant"] == "acme"

    @pytest.mark.asyncio
    async def test_headers_absent_by_default(self):
        events = []
        request = Mock()
        request.method = "GET"
        request.url = Mock()
        request.url.path = "/test"
        request.headers = {"x-tenant": "acme"}
        request.client = None

        logger = AuditLogger(handler=events.append)
        await logger.log_decision(request, "test", True)

        assert events[0].request_headers is None
        assert "headers" not in events[0].to_dict().get("request", {})


class TestResourceContextInclusion:
    """Resource context is opt-in: it may carry user data (emails, document
    attributes) that should not land in logs unreviewed."""

    @pytest.mark.asyncio
    async def test_resource_context_absent_by_default(self):
        events = []

        logger = AuditLogger(handler=events.append)
        await logger.log_decision(
            None, "myapp.GET.test", True, resource_context={"owner_email": "a@b.c"}
        )

        assert events[0].resource_context is None
        assert "resource_context" not in events[0].to_dict()

    @pytest.mark.asyncio
    async def test_resource_context_included_when_opted_in(self):
        events = []

        logger = AuditLogger(handler=events.append, include_resource_context=True)
        await logger.log_decision(
            None, "myapp.GET.test", True, resource_context={"owner_email": "a@b.c"}
        )

        assert events[0].resource_context == {"owner_email": "a@b.c"}
        assert events[0].to_dict()["resource_context"] == {"owner_email": "a@b.c"}


def _audited_app(audit_logger, monkeypatch, *, use_middleware, identity=None, provider=None):
    """App protected by a dependency or the middleware, with Topaz allowing."""
    from unittest.mock import AsyncMock

    from aserto.client import AuthorizerOptions, Identity, IdentityType
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from fastapi_topaz import TopazConfig, TopazMiddleware, require_policy_allowed
    from fastapi_topaz._client import SharedAuthorizerClient

    monkeypatch.setattr(
        SharedAuthorizerClient, "decisions", AsyncMock(return_value={"allowed": True})
    )
    identity = identity or Identity(type=IdentityType.IDENTITY_TYPE_SUB, value="user-1")
    config = TopazConfig(
        authorizer_options=AuthorizerOptions(url="localhost:8282"),
        policy_path_root="testapp",
        identity_provider=lambda r: identity,
        policy_instance_name="test",
        resource_context_provider=provider,
        audit_logger=audit_logger,
    )
    app = FastAPI()
    deps = [] if use_middleware else [Depends(require_policy_allowed(config, "testapp.GET.x"))]

    @app.get("/x", dependencies=deps)
    def route():
        return {"ok": True}

    if use_middleware:
        app.add_middleware(TopazMiddleware, config=config)
    return TestClient(app)


class TestAuditFailuresDoNotChangeResponse:
    """Regression: an audit handler or serialization error turned an allowed
    request into a 500."""

    @pytest.mark.parametrize("use_middleware", [False, True])
    def test_raising_handler_still_returns_200(self, monkeypatch, use_middleware):
        def handler(event):
            raise RuntimeError("audit sink down")

        client = _audited_app(AuditLogger(handler=handler), monkeypatch, use_middleware=use_middleware)
        assert client.get("/x").status_code == 200

    @pytest.mark.parametrize("use_middleware", [False, True])
    def test_unserializable_context_still_returns_200(self, monkeypatch, use_middleware):
        client = _audited_app(
            AuditLogger(include_resource_context=True),
            monkeypatch,
            use_middleware=use_middleware,
            provider=lambda r: {"obj": object()},
        )
        assert client.get("/x").status_code == 200

    def test_to_json_stringifies_unserializable_values(self):
        event = AuditEvent(
            event="authorization.dependency.allowed",
            source="dependency",
            policy_path="p",
            decision="allowed",
            resource_context={"when": object()},
        )
        assert "object object" in json.loads(event.to_json())["resource_context"]["when"]


class TestAuditSecretRedaction:
    """Bearer credentials must not reach audit or debug logs."""

    @pytest.mark.parametrize(
        "header", ["proxy-authorization", "x-api-key", "x-auth-token", "x-csrf-token"]
    )
    @pytest.mark.asyncio
    async def test_credential_headers_redacted(self, header):
        events = []
        request = Mock()
        request.method = "GET"
        request.url = Mock()
        request.url.path = "/test"
        request.headers = {header: "secret-value", "x-tenant": "acme"}
        request.client = None

        await AuditLogger(handler=events.append, include_request_headers=True).log_decision(
            request, "test", True
        )

        headers = events[0].to_dict()["request"]["headers"]
        assert headers[header] == "[REDACTED]"
        assert headers["x-tenant"] == "acme"

    def test_jwt_identity_value_redacted(self, monkeypatch):
        from aserto.client import Identity, IdentityType

        events = []
        client = _audited_app(
            AuditLogger(handler=events.append),
            monkeypatch,
            use_middleware=False,
            identity=Identity(type=IdentityType.IDENTITY_TYPE_JWT, value="eyJ.secret.token"),
        )
        client.get("/x")
        assert events[0].identity_value == "[REDACTED]"

    def test_sub_identity_value_kept(self, monkeypatch):
        events = []
        client = _audited_app(AuditLogger(handler=events.append), monkeypatch, use_middleware=False)
        client.get("/x")
        assert events[0].identity_value == "user-1"

    def test_dependency_debug_logs_omit_identity_value(self, monkeypatch, caplog):
        import logging

        from aserto.client import Identity, IdentityType

        client = _audited_app(
            None,
            monkeypatch,
            use_middleware=False,
            identity=Identity(type=IdentityType.IDENTITY_TYPE_JWT, value="eyJ.secret.token"),
        )
        with caplog.at_level(logging.DEBUG, logger="fastapi_topaz"):
            client.get("/x")

        assert "Authorization check" in caplog.text
        assert "eyJ.secret.token" not in caplog.text

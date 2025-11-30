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
        await logger.log_batch_check(
            None, "document", "doc-123", {"can_read": True}
        )

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

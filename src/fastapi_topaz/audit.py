"""
Audit logging for authorization decisions.

Provides structured JSON logging for compliance, security monitoring, and debugging.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Union

from fastapi import Request

logger = logging.getLogger("fastapi_topaz.audit")

__all__ = ["AuditLogger", "AuditEvent"]


@dataclass
class AuditEvent:
    """Structured audit event for authorization decisions."""

    event: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    level: str = "INFO"
    request_id: str | None = None
    source: str = "dependency"  # middleware, dependency, manual

    # Identity
    identity_type: str | None = None
    identity_value: str | None = None
    anonymous: bool = False

    # Authorization
    policy_path: str | None = None
    decision: str | None = None  # allowed, denied
    check_type: str = "policy"  # policy, rebac, rebac_batch
    cached: bool = False
    latency_ms: float | None = None

    # Request
    method: str | None = None
    path: str | None = None
    route_pattern: str | None = None
    client_ip: str | None = None

    # Resource (ReBAC)
    object_type: str | None = None
    object_id: str | None = None
    relation: str | None = None
    subject_type: str | None = None

    # Additional
    reason: str | None = None
    results: dict[str, bool] | None = None  # For batch checks
    resource_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to structured dict for logging."""
        data: dict[str, Any] = {
            "timestamp": self.timestamp,
            "level": self.level,
            "event": self.event,
            "source": self.source,
        }
        if self.request_id:
            data["request_id"] = self.request_id

        # Identity block
        if self.identity_value is not None:
            data["identity"] = {
                "type": self.identity_type,
                "value": self.identity_value,
                "anonymous": self.anonymous,
            }
        elif self.anonymous:
            data["identity"] = None

        # Authorization block
        auth: dict[str, Any] = {}
        if self.policy_path:
            auth["policy_path"] = self.policy_path
        if self.decision:
            auth["decision"] = self.decision
        if self.check_type != "policy":
            auth["check_type"] = self.check_type
        if self.cached:
            auth["cached"] = True
        if self.latency_ms is not None:
            auth["latency_ms"] = round(self.latency_ms, 2)
        if auth:
            data["authorization"] = auth

        # Request block
        req: dict[str, Any] = {}
        if self.method:
            req["method"] = self.method
        if self.path:
            req["path"] = self.path
        if self.route_pattern:
            req["route_pattern"] = self.route_pattern
        if self.client_ip:
            req["ip"] = self.client_ip
        if req:
            data["request"] = req

        # Resource block (ReBAC)
        if self.object_type or self.object_id or self.relation:
            data["resource"] = {
                k: v for k, v in {
                    "object_type": self.object_type,
                    "object_id": self.object_id,
                    "relation": self.relation,
                    "subject_type": self.subject_type,
                }.items() if v is not None
            }

        # Additional fields
        if self.reason:
            data["reason"] = self.reason
        if self.results:
            data["results"] = self.results
        if self.resource_context:
            data["resource_context"] = self.resource_context

        return data

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


# Type for custom handlers
AuditHandler = Callable[[AuditEvent], Union[Awaitable[None], None]]


@dataclass
class AuditLogger:
    """
    Audit logger for authorization decisions.

    Args:
        log_allowed: Log successful authorizations
        log_denied: Log denied authorizations
        log_skipped: Log skipped/excluded routes
        log_unauthenticated: Log 401 events
        log_manual_checks: Log is_allowed(), check_relations()
        level_allowed: Log level for allowed events
        level_denied: Log level for denied events
        level_unauthenticated: Log level for 401 events
        level_skipped: Log level for skipped events
        include_resource_context: Include resource context in logs
        include_request_headers: Include HTTP headers (privacy concern)
        handler: Custom async handler for events
    """

    log_allowed: bool = True
    log_denied: bool = True
    log_skipped: bool = False
    log_unauthenticated: bool = True
    log_manual_checks: bool = False

    level_allowed: str = "INFO"
    level_denied: str = "WARNING"
    level_unauthenticated: str = "WARNING"
    level_skipped: str = "DEBUG"

    include_resource_context: bool = True
    include_request_headers: bool = False

    handler: AuditHandler | None = None

    def _get_request_id(self, request: Request | None) -> str:
        """Get or generate request ID."""
        if request is None:
            return str(uuid.uuid4())[:8]
        # Check common headers
        for header in ("x-request-id", "x-correlation-id", "request-id"):
            if header in request.headers:
                return request.headers[header]
        # Generate and store
        if not hasattr(request.state, "request_id"):
            request.state.request_id = str(uuid.uuid4())[:8]
        return request.state.request_id

    def _get_client_ip(self, request: Request | None) -> str | None:
        """Extract client IP from request."""
        if request is None:
            return None
        # Check forwarded headers
        for header in ("x-forwarded-for", "x-real-ip"):
            if header in request.headers:
                return request.headers[header].split(",")[0].strip()
        if request.client:
            return request.client.host
        return None

    async def _emit(self, event: AuditEvent) -> None:
        """Emit event to handler or default logger."""
        if self.handler:
            result = self.handler(event)
            if result is not None:
                await result
        else:
            level = getattr(logging, event.level.upper(), logging.INFO)
            logger.log(level, event.to_json())

    async def log_decision(
        self,
        request: Request | None,
        policy_path: str,
        allowed: bool,
        *,
        source: str = "dependency",
        check_type: str = "policy",
        cached: bool = False,
        latency_ms: float | None = None,
        identity_type: str | None = None,
        identity_value: str | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        relation: str | None = None,
        subject_type: str | None = None,
        resource_context: dict[str, Any] | None = None,
    ) -> None:
        """Log an authorization decision."""
        if allowed and not self.log_allowed:
            return
        if not allowed and not self.log_denied:
            return

        decision = "allowed" if allowed else "denied"
        event_name = f"authorization.{source}.{decision}"
        level = self.level_allowed if allowed else self.level_denied

        event = AuditEvent(
            event=event_name,
            level=level,
            request_id=self._get_request_id(request),
            source=source,
            identity_type=identity_type,
            identity_value=identity_value,
            policy_path=policy_path,
            decision=decision,
            check_type=check_type,
            cached=cached,
            latency_ms=latency_ms,
            method=request.method if request else None,
            path=str(request.url.path) if request else None,
            client_ip=self._get_client_ip(request),
            object_type=object_type,
            object_id=object_id,
            relation=relation,
            subject_type=subject_type,
            resource_context=resource_context if self.include_resource_context else None,
        )

        await self._emit(event)

    async def log_batch_check(
        self,
        request: Request | None,
        object_type: str,
        object_id: str,
        results: dict[str, bool],
        *,
        latency_ms: float | None = None,
        identity_value: str | None = None,
    ) -> None:
        """Log batch relation check results."""
        if not self.log_manual_checks:
            return

        event = AuditEvent(
            event="authorization.check.relations",
            level=self.level_allowed,
            request_id=self._get_request_id(request),
            source="manual",
            identity_value=identity_value,
            check_type="rebac_batch",
            latency_ms=latency_ms,
            method=request.method if request else None,
            path=str(request.url.path) if request else None,
            client_ip=self._get_client_ip(request),
            object_type=object_type,
            object_id=object_id,
            results=results,
        )

        await self._emit(event)

    async def log_unauthenticated_event(
        self,
        request: Request | None,
        reason: str = "missing_identity",
    ) -> None:
        """Log unauthenticated access attempt."""
        if not self.log_unauthenticated:
            return

        event = AuditEvent(
            event="authorization.middleware.unauthenticated",
            level=self.level_unauthenticated,
            request_id=self._get_request_id(request),
            source="middleware",
            anonymous=True,
            method=request.method if request else None,
            path=str(request.url.path) if request else None,
            client_ip=self._get_client_ip(request),
            reason=reason,
        )

        await self._emit(event)

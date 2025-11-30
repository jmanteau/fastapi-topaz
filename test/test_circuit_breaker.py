"""
Tests for circuit breaker functionality.

The circuit breaker protects against cascading failures when Topaz is unavailable.
It tracks authorization failures and "opens" to prevent further requests when a
threshold is exceeded, then gradually recovers.

States:
- CLOSED: Normal operation, requests pass through to authorizer
- OPEN: Authorizer is failing, use fallback strategy instead
- HALF_OPEN: Testing recovery, allow limited requests to check if authorizer recovered

Test organization:
- TestCircuitBreakerStates: State machine transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- TestCircuitBreakerFallback: Fallback strategies (deny, allow, cache_then_deny, custom)
- TestCircuitBreakerStatus: Status reporting for monitoring
- TestCircuitBreakerCallbacks: State change event callbacks
- TestCircuitBreakerEdgeCases: Edge cases and error handling
- TestCircuitBreakerIntegration: Integration with TopazConfig
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from fastapi_topaz import TopazConfig, require_policy_allowed
from fastapi_topaz.circuit_breaker import CircuitBreaker, CircuitState


@pytest.fixture
def authorizer_options():
    return AuthorizerOptions(url="localhost:8282", tenant_id="test", api_key="key")


@pytest.fixture
def identity_provider():
    return lambda req: Identity(type=IdentityType.IDENTITY_TYPE_SUB, value="user-123")


@pytest.fixture
def circuit_breaker():
    """Circuit breaker with 3-failure threshold and 1-second recovery."""
    return CircuitBreaker(failure_threshold=3, recovery_timeout=1.0, fallback="deny")


class TestCircuitBreakerStates:
    """
    Circuit breaker state machine transitions.

    State transitions:
    - CLOSED → OPEN: After failure_threshold consecutive failures
    - OPEN → HALF_OPEN: After recovery_timeout elapses
    - HALF_OPEN → CLOSED: After success_threshold successes
    - HALF_OPEN → OPEN: On any failure during recovery testing
    """

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self, circuit_breaker):
        assert circuit_breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_failure_threshold(self, circuit_breaker):
        for _ in range(3):
            await circuit_breaker.record_failure(ConnectionError("test"))
        assert circuit_breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, circuit_breaker):
        await circuit_breaker.record_failure(ConnectionError("test"))
        await circuit_breaker.record_failure(ConnectionError("test"))
        await circuit_breaker.record_success()
        await circuit_breaker.record_failure(ConnectionError("test"))
        assert circuit_breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self, circuit_breaker):
        for _ in range(3):
            await circuit_breaker.record_failure(ConnectionError("test"))
        assert circuit_breaker.state == CircuitState.OPEN

        await asyncio.sleep(1.1)
        should_allow = await circuit_breaker.should_allow_request()
        assert should_allow is True
        assert circuit_breaker.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_closes_after_success_in_half_open(self, circuit_breaker):
        circuit_breaker.success_threshold = 1
        for _ in range(3):
            await circuit_breaker.record_failure(ConnectionError("test"))
        await asyncio.sleep(1.1)
        await circuit_breaker.should_allow_request()
        await circuit_breaker.record_success()
        assert circuit_breaker.state == CircuitState.CLOSED


class TestCircuitBreakerFallback:
    """
    Fallback strategies when circuit is OPEN.

    Available strategies:
    - "deny": Always deny access (fail-safe)
    - "allow": Always allow access (fail-open, use with caution)
    - "cache_then_deny": Use cached decision if available, else deny
    - "cache_then_allow": Use cached decision if available, else allow
    - callable: Custom function for complex fallback logic
    """

    @pytest.mark.asyncio
    async def test_deny_fallback(self):
        cb = CircuitBreaker(fallback="deny")
        result = await cb.get_fallback_decision(
            Mock(), "policy", {}, None, ConnectionError()
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_allow_fallback(self):
        cb = CircuitBreaker(fallback="allow")
        result = await cb.get_fallback_decision(
            Mock(), "policy", {}, None, ConnectionError()
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_cache_then_deny_with_cache(self):
        cb = CircuitBreaker(fallback="cache_then_deny")
        result = await cb.get_fallback_decision(
            Mock(), "policy", {}, True, ConnectionError()
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_cache_then_deny_without_cache(self):
        cb = CircuitBreaker(fallback="cache_then_deny")
        result = await cb.get_fallback_decision(
            Mock(), "policy", {}, None, ConnectionError()
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_custom_callable_fallback(self):
        async def custom_fb(req, path, ctx, cached, err):
            return path == "allowed.policy"

        cb = CircuitBreaker(fallback=custom_fb)
        result = await cb.get_fallback_decision(
            Mock(), "allowed.policy", {}, None, ConnectionError()
        )
        assert result is True


class TestCircuitBreakerStatus:
    """
    Status reporting for monitoring and health checks.

    CircuitBreakerStatus includes current state, failure count, and whether
    the circuit is open. Use for dashboards and alerting.
    """

    @pytest.mark.asyncio
    async def test_status_reports_state(self, circuit_breaker):
        status = circuit_breaker.status()
        assert status.state == "closed"
        assert status.is_open is False

    @pytest.mark.asyncio
    async def test_status_after_failures(self, circuit_breaker):
        for _ in range(3):
            await circuit_breaker.record_failure(ConnectionError("test"))
        status = circuit_breaker.status()
        assert status.state == "open"
        assert status.failure_count == 3
        assert status.is_open is True


class TestCircuitBreakerCallbacks:
    """
    State change event callbacks.

    on_state_change is called with (old_state, new_state, reason) when the circuit
    transitions. Useful for logging, alerting, or custom recovery logic.
    Callback errors are caught to prevent breaking the circuit breaker.
    """

    @pytest.mark.asyncio
    async def test_on_state_change_callback(self):
        changes = []

        def on_change(old, new, reason):
            changes.append((old, new, reason))

        cb = CircuitBreaker(
            failure_threshold=2,
            on_state_change=on_change,
        )

        await cb.record_failure(ConnectionError("test"))
        await cb.record_failure(ConnectionError("test"))

        assert len(changes) == 1
        assert changes[0] == ("closed", "open", "failure_threshold_exceeded")

    @pytest.mark.asyncio
    async def test_on_state_change_error_handling(self):
        """Callback errors should be caught and not break circuit breaker."""
        def bad_callback(old, new, reason):
            raise ValueError("callback error")

        cb = CircuitBreaker(
            failure_threshold=1,
            on_state_change=bad_callback,
        )

        # Should not raise despite bad callback
        await cb.record_failure(ConnectionError("test"))
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerEdgeCases:
    """
    Edge cases and error handling.

    Tests for reset, exception filtering, unknown fallback strategies,
    no_stale_for patterns, and half-open request limiting.
    """

    @pytest.mark.asyncio
    async def test_reset(self):
        cb = CircuitBreaker(failure_threshold=2)
        await cb.record_failure(ConnectionError("test"))
        await cb.record_failure(ConnectionError("test"))
        assert cb.state == CircuitState.OPEN

        await cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_is_failure_exception(self):
        cb = CircuitBreaker(failure_exceptions=[ConnectionError, TimeoutError])
        assert cb.is_failure_exception(ConnectionError("test")) is True
        assert cb.is_failure_exception(TimeoutError("test")) is True
        assert cb.is_failure_exception(ValueError("test")) is False

    @pytest.mark.asyncio
    async def test_cache_then_allow_fallback(self):
        cb = CircuitBreaker(fallback="cache_then_allow")
        result = await cb.get_fallback_decision(
            Mock(), "policy", {}, None, ConnectionError()
        )
        assert result is True  # Allow when no cache

    @pytest.mark.asyncio
    async def test_unknown_fallback_strategy(self):
        cb = CircuitBreaker(fallback="unknown_strategy")
        result = await cb.get_fallback_decision(
            Mock(), "policy", {}, None, ConnectionError()
        )
        assert result is False  # Defaults to deny

    @pytest.mark.asyncio
    async def test_no_stale_for_patterns(self):
        cb = CircuitBreaker(
            fallback="cache_then_deny",
            no_stale_for=["*.admin.*"],
        )
        # Should ignore cache for admin paths
        result = await cb.get_fallback_decision(
            Mock(), "app.admin.delete", {}, True, ConnectionError()
        )
        assert result is False  # Denied because cache ignored

    @pytest.mark.asyncio
    async def test_half_open_limits_requests(self):
        cb = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.01,
            half_open_max_requests=1,
        )
        await cb.record_failure(ConnectionError("test"))
        await asyncio.sleep(0.02)

        # First request in half-open allowed
        assert await cb.should_allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

        # Second request blocked
        assert await cb.should_allow_request() is False


@pytest.mark.asyncio
class TestCircuitBreakerIntegration:
    """
    Circuit breaker integration with TopazConfig.

    Tests that the circuit breaker properly integrates with TopazConfig to protect
    FastAPI routes from authorizer failures.
    """

    async def test_circuit_opens_on_connection_errors(
        self, authorizer_options, identity_provider, monkeypatch
    ):
        cb = CircuitBreaker(failure_threshold=2, fallback="deny")
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="test",
            identity_provider=identity_provider,
            policy_instance_name="test",
            circuit_breaker=cb,
        )

        def failing_client(self, req):
            mock = Mock()
            mock.decisions = AsyncMock(side_effect=ConnectionError("down"))
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", failing_client)

        app = FastAPI()

        @app.get("/test")
        async def route(request: Request, _=Depends(require_policy_allowed(config, "test"))):
            return {"ok": True}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # First two failures open the circuit
            await client.get("/test")
            await client.get("/test")
            assert cb.state == CircuitState.OPEN

    async def test_uses_stale_cache_when_open(
        self, authorizer_options, identity_provider, monkeypatch
    ):
        cb = CircuitBreaker(failure_threshold=1, fallback="cache_then_deny")
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="test",
            identity_provider=identity_provider,
            policy_instance_name="test",
            circuit_breaker=cb,
        )

        call_count = [0]

        def client_factory(self, req):
            call_count[0] += 1
            mock = Mock()
            if call_count[0] == 1:
                mock.decisions = AsyncMock(return_value={"allowed": True})
            else:
                mock.decisions = AsyncMock(side_effect=ConnectionError("down"))
            return mock

        monkeypatch.setattr(TopazConfig, "create_client", client_factory)

        app = FastAPI()

        @app.get("/test")
        async def route(request: Request, _=Depends(require_policy_allowed(config, "test"))):
            return {"ok": True}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # First call succeeds and caches
            resp = await client.get("/test")
            assert resp.status_code == 200

            # Second call fails but uses stale cache
            resp = await client.get("/test")
            assert resp.status_code == 200  # Stale cache hit

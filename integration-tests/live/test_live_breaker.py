"""Live tests for gRPC-aware circuit breaker failure detection (fix C1).

The unit suite mocks above the wire, so it never sees a real
grpc.aio.AioRpcError. These tests prove that real DEADLINE_EXCEEDED and
UNAVAILABLE errors from a live (or stopped) Topaz trip the breaker, that the
full open -> half-open -> closed cycle works across a real outage and
recovery, and that stale cached decisions are served during an outage.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from conftest import AUTH_POLICY

from fastapi_topaz import CircuitBreaker, CircuitState


async def test_deadline_counts_as_breaker_failure(make_config, make_request):
    breaker = CircuitBreaker(failure_threshold=1, fallback="deny")
    config = make_config(circuit_breaker=breaker, check_timeout=0.000001)

    # The real AioRpcError(DEADLINE_EXCEEDED) must be caught by
    # is_failure_exception and converted to a fallback deny, not re-raised.
    allowed = await config.is_allowed(make_request("alice"), AUTH_POLICY)

    assert allowed is False
    assert breaker.state is CircuitState.OPEN


@pytest.mark.disruptive
async def test_unavailable_counts_as_breaker_failure(make_config, make_request, topaz_control):
    breaker = CircuitBreaker(failure_threshold=2, fallback="deny")
    config = make_config(circuit_breaker=breaker, check_timeout=5.0)

    try:
        topaz_control.stop()

        for _ in range(2):
            allowed = await config.is_allowed(make_request("alice"), AUTH_POLICY)
            assert allowed is False

        assert breaker.state is CircuitState.OPEN
    finally:
        topaz_control.start()
        topaz_control.wait_ready()


@pytest.mark.disruptive
async def test_full_breaker_cycle(make_config, make_request, topaz_control):
    transitions: list[tuple[str, str]] = []
    breaker = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout=2.0,
        success_threshold=1,
        fallback="deny",
        on_state_change=lambda old, new, _reason: transitions.append((old, new)),
    )
    config = make_config(circuit_breaker=breaker, check_timeout=5.0)

    try:
        # Healthy call: circuit stays closed
        assert await config.is_allowed(make_request("alice"), AUTH_POLICY)
        assert breaker.state is CircuitState.CLOSED

        # Outage: first failing call opens the circuit
        topaz_control.stop()
        assert not await config.is_allowed(make_request("alice"), AUTH_POLICY)
        assert breaker.state is CircuitState.OPEN

        # While open, calls short-circuit without touching the wire
        start = time.monotonic()
        assert not await config.is_allowed(make_request("alice"), AUTH_POLICY)
        assert time.monotonic() - start < 1.0
        assert breaker.state is CircuitState.OPEN

        # Recovery: restart topaz, wait past recovery_timeout, then retry.
        # The gRPC channel needs its own reconnect backoff after the outage,
        # so a half-open probe may fail and re-open the circuit; keep trying
        # within a generous budget.
        topaz_control.start()
        topaz_control.wait_ready()
        await asyncio.sleep(breaker.recovery_timeout + 0.5)

        deadline = time.monotonic() + 30.0
        recovered = False
        while time.monotonic() < deadline:
            if await config.is_allowed(make_request("alice"), AUTH_POLICY):
                recovered = True
                break
            await asyncio.sleep(breaker.recovery_timeout + 0.5)

        assert recovered, "circuit never recovered after topaz came back"
        assert breaker.state is CircuitState.CLOSED
        assert ("closed", "open") in transitions
        assert ("open", "half_open") in transitions
        assert ("half_open", "closed") in transitions
    finally:
        topaz_control.restore()


@pytest.mark.disruptive
async def test_stale_cache_serves_allow_during_outage(make_config, make_request, topaz_control):
    breaker = CircuitBreaker(
        failure_threshold=1,
        fallback="cache_then_deny",
        serve_stale_cache=True,
    )
    config = make_config(circuit_breaker=breaker, check_timeout=5.0)

    try:
        # Prime the stale cache with a real allow for alice
        assert await config.is_allowed(make_request("alice"), AUTH_POLICY)

        topaz_control.stop()

        # alice is served her stale allow despite the outage
        assert await config.is_allowed(make_request("alice"), AUTH_POLICY)
        # bob was never cached, so cache_then_deny falls through to deny
        assert not await config.is_allowed(make_request("bob"), AUTH_POLICY)
    finally:
        topaz_control.start()
        topaz_control.wait_ready()

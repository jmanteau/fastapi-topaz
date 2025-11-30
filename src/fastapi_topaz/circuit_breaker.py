"""
Circuit Breaker pattern for graceful degradation when Topaz is unavailable.

Provides resilience by detecting failures and preventing cascading failures.
Integrates with DecisionCache to serve stale cached decisions during outages.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar, Union

from fastapi import Request

logger = logging.getLogger("fastapi_topaz.circuit_breaker")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, using fallback
    HALF_OPEN = "half_open"  # Testing if service recovered


# Fallback strategy type
FallbackStrategy = Union[
    str,
    Callable[
        [Request, str, dict[str, Any], Union[bool, None], Exception],
        bool,
    ],
]


@dataclass
class CircuitStatus:
    """Current status of the circuit breaker for health checks."""

    state: str
    failure_count: int
    success_count: int
    last_failure_time: float | None
    last_success_time: float | None
    open_since: float | None

    @property
    def is_open(self) -> bool:
        """Check if circuit is currently open."""
        return self.state == CircuitState.OPEN.value


@dataclass
class CircuitBreaker:
    """
    Circuit breaker configuration for Topaz authorization.

    Prevents cascading failures when Topaz is unavailable by opening the circuit
    after a threshold of failures, using fallback strategies, and automatically
    testing for recovery.

    Args:
        failure_threshold: Number of consecutive failures before opening circuit
        success_threshold: Number of successes in half-open before closing
        recovery_timeout: Seconds to wait before transitioning to half-open
        fallback: Strategy when circuit is open ("cache_then_deny", "cache_then_allow",
                  "deny", "allow", or custom callable)
        serve_stale_cache: Whether to serve expired cache entries when open
        stale_cache_ttl: Maximum age (seconds) of stale cache to serve
        failure_exceptions: Exception types that count as failures
        timeout_ms: Consider timeout after this many milliseconds
        on_state_change: Callback when circuit state changes
        on_fallback: Callback when fallback is used
        half_open_max_requests: Number of test requests allowed in half-open state

    Example:
        ```python
        config = TopazConfig(
            ...,
            circuit_breaker=CircuitBreaker(
                failure_threshold=5,
                recovery_timeout=30,
                fallback="cache_then_deny",
            ),
        )
        ```
    """

    # Thresholds
    failure_threshold: int = 5
    success_threshold: int = 2
    recovery_timeout: float = 30.0

    # Fallback strategy
    fallback: FallbackStrategy = "cache_then_deny"

    # Cache integration
    serve_stale_cache: bool = True
    stale_cache_ttl: float = 300.0
    cache_priority: list[str] | None = None
    no_stale_for: list[str] | None = None

    # Failure detection
    failure_exceptions: list[type] = field(
        default_factory=lambda: [ConnectionError, TimeoutError, OSError]
    )
    timeout_ms: int = 5000

    # Callbacks
    on_state_change: Callable[[str, str, str], None] | None = None
    on_fallback: Callable[[Request, str, bool | None, bool], None] | None = None

    # Advanced
    half_open_max_requests: int = 1

    # Internal state (not part of config)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False, repr=False)
    _failure_count: int = field(default=0, init=False, repr=False)
    _success_count: int = field(default=0, init=False, repr=False)
    _last_failure_time: float | None = field(default=None, init=False, repr=False)
    _last_success_time: float | None = field(default=None, init=False, repr=False)
    _open_since: float | None = field(default=None, init=False, repr=False)
    _half_open_requests: int = field(default=0, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    def status(self) -> CircuitStatus:
        """Get current circuit status for health checks."""
        return CircuitStatus(
            state=self._state.value,
            failure_count=self._failure_count,
            success_count=self._success_count,
            last_failure_time=self._last_failure_time,
            last_success_time=self._last_success_time,
            open_since=self._open_since,
        )

    async def _transition_to(self, new_state: CircuitState, reason: str) -> None:
        """Transition to a new state with logging and callback."""
        old_state = self._state
        if old_state == new_state:
            return

        self._state = new_state

        if new_state == CircuitState.OPEN:
            self._open_since = time.monotonic()
            self._half_open_requests = 0
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._open_since = None
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_requests = 0

        logger.warning(
            f"Circuit breaker state change: {old_state.value} -> {new_state.value} "
            f"(reason: {reason})"
        )

        if self.on_state_change:
            try:
                self.on_state_change(old_state.value, new_state.value, reason)
            except Exception as e:
                logger.error(f"Error in on_state_change callback: {e}")

    async def record_success(self) -> None:
        """Record a successful authorization call."""
        async with self._lock:
            self._last_success_time = time.monotonic()
            self._failure_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    await self._transition_to(CircuitState.CLOSED, "test_succeeded")

    async def record_failure(self, exception: Exception) -> None:
        """Record a failed authorization call."""
        async with self._lock:
            self._last_failure_time = time.monotonic()
            self._failure_count += 1
            self._success_count = 0

            logger.warning(
                f"Circuit breaker recorded failure #{self._failure_count}: {exception}"
            )

            if self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    await self._transition_to(
                        CircuitState.OPEN, "failure_threshold_exceeded"
                    )
            elif self._state == CircuitState.HALF_OPEN:
                await self._transition_to(CircuitState.OPEN, "test_failed")

    async def should_allow_request(self) -> bool:
        """
        Check if a request should be allowed through to Topaz.

        Returns True if the circuit is closed or if we should test in half-open.
        Returns False if the circuit is open and fallback should be used.
        """
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if self._open_since is not None:
                    elapsed = time.monotonic() - self._open_since
                    if elapsed >= self.recovery_timeout:
                        await self._transition_to(
                            CircuitState.HALF_OPEN, "recovery_timeout_expired"
                        )
                        self._half_open_requests = 1
                        return True
                return False

            if self._state == CircuitState.HALF_OPEN:
                # Allow limited requests in half-open state
                if self._half_open_requests < self.half_open_max_requests:
                    self._half_open_requests += 1
                    return True
                return False

            return False

    def is_failure_exception(self, exc: Exception) -> bool:
        """Check if an exception should count as a circuit breaker failure."""
        return any(isinstance(exc, exc_type) for exc_type in self.failure_exceptions)

    async def get_fallback_decision(
        self,
        request: Request,
        policy_path: str,
        resource_context: dict[str, Any],
        cached_decision: bool | None,
        error: Exception,
    ) -> bool:
        """
        Get the fallback decision when circuit is open.

        Args:
            request: The FastAPI request
            policy_path: The policy path being checked
            resource_context: The resource context
            cached_decision: Cached decision (may be stale), or None if not cached
            error: The exception that caused the fallback

        Returns:
            Authorization decision (True/False)
        """
        # Check no_stale_for patterns
        if cached_decision is not None and self.no_stale_for:
            import fnmatch

            for pattern in self.no_stale_for:
                if fnmatch.fnmatch(policy_path, pattern):
                    cached_decision = None
                    break

        if callable(self.fallback):
            result = self.fallback(
                request, policy_path, resource_context, cached_decision, error
            )
            # Support both sync and async callables
            if asyncio.iscoroutine(result):
                result = await result  # type: ignore[misc]
            return result

        strategy = self.fallback

        if strategy == "cache_then_deny":
            if cached_decision is not None:
                return cached_decision
            return False

        if strategy == "cache_then_allow":
            if cached_decision is not None:
                return cached_decision
            return True

        if strategy == "deny":
            return False

        if strategy == "allow":
            return True

        # Default to deny for unknown strategies
        logger.error(f"Unknown fallback strategy: {strategy}, defaulting to deny")
        return False

    async def reset(self) -> None:
        """Reset the circuit breaker to initial state."""
        async with self._lock:
            await self._transition_to(CircuitState.CLOSED, "manual_reset")
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._last_success_time = None
            self._open_since = None
            self._half_open_requests = 0


# Type variable for generic typing
T = TypeVar("T")

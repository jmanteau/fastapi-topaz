"""Tests for TopazConfig lifecycle, stale cache safety, and semaphore init."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType
from fastapi import Request

from fastapi_topaz._policy import normalize_hyphens
from fastapi_topaz.cache import DecisionCache
from fastapi_topaz.config import TopazConfig, _resolve_id_source


def _make_config(**overrides):
    defaults = dict(
        authorizer_options=AuthorizerOptions(url="localhost:8282"),
        policy_path_root="test",
        identity_provider=lambda r: Identity(type=IdentityType.IDENTITY_TYPE_SUB, value="user-1"),
        policy_instance_name="test",
    )
    defaults.update(overrides)
    return TopazConfig(**defaults)


class TestTopazConfigLifecycle:
    """Tests for close() and async context manager (H3 fix)."""

    @pytest.mark.asyncio
    async def test_close_calls_pool_and_cache(self):
        mock_pool = Mock()
        mock_pool.close = AsyncMock()
        mock_pool.configure = Mock()
        cache = DecisionCache()

        config = _make_config(connection_pool=mock_pool, decision_cache=cache)
        await config.close()

        mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_safe_without_pool_or_cache(self):
        config = _make_config()
        await config.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        mock_pool = Mock()
        mock_pool.close = AsyncMock()
        mock_pool.configure = Mock()

        config = _make_config(connection_pool=mock_pool)
        async with config as ctx:
            assert ctx is config
        mock_pool.close.assert_awaited_once()


class TestStaleCacheSafety:
    """Tests for async lock on stale cache (H1 fix)."""

    @pytest.mark.asyncio
    async def test_stale_cache_lock_created_lazily(self):
        """Regression (B6): the lock is created on first use inside a running
        loop, so it never binds a stale loop on Python 3.9."""
        config = _make_config()
        assert config._stale_cache_lock is None
        lock = config._get_stale_cache_lock()
        assert isinstance(lock, asyncio.Lock)
        assert config._get_stale_cache_lock() is lock

    @pytest.mark.asyncio
    async def test_concurrent_stale_cache_access(self):
        """Concurrent _set and _get should not corrupt data."""
        from fastapi_topaz.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(serve_stale_cache=True, stale_cache_ttl=300)
        config = _make_config(circuit_breaker=cb)

        async def write_and_read(i: int):
            await config._set_stale_cached(f"user-{i}", "policy", "allowed", None, True)
            result = await config._get_stale_cached(f"user-{i}", "policy", "allowed", None)
            return result

        results = await asyncio.gather(*[write_and_read(i) for i in range(20)])
        assert all(r is True for r in results)


class TestSemaphoreLazyInit:
    """Regression (B6): asyncio primitives are created lazily on first use.

    On Python 3.9 asyncio.Semaphore/Lock bind the event loop active at
    creation time; configs are typically created at module import, outside
    any loop, so eager creation breaks under a different running loop.
    """

    def test_semaphore_not_created_at_init(self):
        config = _make_config()
        assert config._semaphore is None

    @pytest.mark.asyncio
    async def test_semaphore_respects_max_concurrent(self):
        config = _make_config(max_concurrent_checks=5)
        assert config._get_semaphore()._value == 5

    @pytest.mark.asyncio
    async def test_semaphore_default_value(self):
        config = _make_config()
        assert config._get_semaphore()._value == 10

    @pytest.mark.asyncio
    async def test_semaphore_created_once(self):
        config = _make_config()
        sem = config._get_semaphore()
        assert config._get_semaphore() is sem


class TestLocalsAntiPatternFix:
    """Test that result tracking uses explicit variable (H2 fix)."""

    @pytest.mark.asyncio
    async def test_result_tracked_explicitly(self):
        """check_decision should track result without locals()."""
        config = _make_config()

        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(return_value={"allowed": True})
        config._authorizer = mock_authorizer

        from unittest.mock import MagicMock

        request = MagicMock()
        request.path_params = {}
        result = await config.check_decision(request, "test.GET.docs", "allowed")
        assert result is True


class TestPolicyPathNormalizer:
    """Tests for policy_path_normalizer on TopazConfig."""

    def test_policy_path_normalizer_default_none(self):
        """Default value of policy_path_normalizer should be None."""
        config = _make_config()
        assert config.policy_path_normalizer is None

    def test_policy_path_for_uses_normalizer(self):
        """policy_path_for() should apply normalizer when set."""
        config = _make_config(policy_path_normalizer=normalize_hyphens)
        result = config.policy_path_for("GET", "/aircraft-programs")
        assert result == "test.GET.aircraft_programs"

    def test_policy_path_for_without_normalizer(self):
        """policy_path_for() should leave hyphens when no normalizer set."""
        config = _make_config()
        result = config.policy_path_for("GET", "/aircraft-programs")
        assert result == "test.GET.aircraft-programs"

    def test_policy_path_normalizer_custom_callable(self):
        """Custom callable normalizer should be applied."""
        config = _make_config(
            policy_path_normalizer=lambda p: p.replace("-", "_").replace(".", "_", 1),
        )
        # Just verifying it's called - the exact transform doesn't matter
        result = config.policy_path_for("GET", "/test-path")
        assert "-" not in result


class TestCircuitMetricsAutoWiring:
    """D5: circuit breaker metrics are recorded automatically when metrics
    are configured and the user has not installed an on_state_change callback."""

    def test_auto_wires_on_state_change(self):
        from fastapi_topaz.circuit_breaker import CircuitBreaker

        metrics = Mock()
        cb = CircuitBreaker()
        _make_config(metrics=metrics, circuit_breaker=cb)

        assert cb.on_state_change is not None
        cb.on_state_change("closed", "open", "failure_threshold_exceeded")
        metrics.record_circuit_transition.assert_called_once_with("closed", "open")
        metrics.set_circuit_state.assert_called_once_with(1)

    def test_state_gauge_values(self):
        from fastapi_topaz.circuit_breaker import CircuitBreaker

        metrics = Mock()
        cb = CircuitBreaker()
        _make_config(metrics=metrics, circuit_breaker=cb)

        cb.on_state_change("open", "half_open", "recovery_timeout_expired")
        metrics.set_circuit_state.assert_called_with(2)
        cb.on_state_change("half_open", "closed", "test_succeeded")
        metrics.set_circuit_state.assert_called_with(0)

    def test_user_callback_not_overwritten(self):
        from fastapi_topaz.circuit_breaker import CircuitBreaker

        user_callback = Mock()
        cb = CircuitBreaker(on_state_change=user_callback)
        _make_config(metrics=Mock(), circuit_breaker=cb)

        assert cb.on_state_change is user_callback

    def test_no_wiring_without_metrics(self):
        from fastapi_topaz.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker()
        _make_config(circuit_breaker=cb)

        assert cb.on_state_change is None


class TestCacheSizeGauge:
    """D5: check_decision updates the cache-size gauge after caching a decision."""

    @pytest.mark.asyncio
    async def test_set_cache_size_called_after_cache_store(self):
        from unittest.mock import MagicMock

        metrics = Mock()
        cache = DecisionCache()
        config = _make_config(metrics=metrics, decision_cache=cache)

        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(return_value={"allowed": True})
        config._authorizer = mock_authorizer

        request = MagicMock()
        request.path_params = {}
        await config.check_decision(request, "test.GET.docs", "allowed")

        metrics.set_cache_size.assert_called_once_with(1)
        assert cache.size() == 1

    @pytest.mark.asyncio
    async def test_set_cache_size_not_called_without_cache(self):
        from unittest.mock import MagicMock

        metrics = Mock()
        config = _make_config(metrics=metrics)

        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(return_value={"allowed": True})
        config._authorizer = mock_authorizer

        request = MagicMock()
        request.path_params = {}
        await config.check_decision(request, "test.GET.docs", "allowed")

        metrics.set_cache_size.assert_not_called()


def _make_request(path_params=None, headers=None, query_string=b"") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/docs/1",
        "path_params": path_params or {},
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "query_string": query_string,
    }
    return Request(scope)


class TestResolveIdSource:
    """Regression (B5): empty resolved object IDs raise instead of yielding ''."""

    def test_path_param_resolves(self):
        request = _make_request(path_params={"doc_id": "doc-1"})
        assert _resolve_id_source("doc_id", request) == "doc-1"

    def test_missing_path_param_raises(self):
        request = _make_request(path_params={"doc_id": "doc-1"})
        with pytest.raises(ValueError, match="'id'.*doc_id"):
            _resolve_id_source("id", request)

    def test_header_resolves(self):
        request = _make_request(headers={"X-Org-Id": "org-1"})
        assert _resolve_id_source("header:X-Org-Id", request) == "org-1"

    def test_missing_header_raises(self):
        request = _make_request()
        with pytest.raises(ValueError, match="X-Org-Id"):
            _resolve_id_source("header:X-Org-Id", request)

    def test_query_resolves(self):
        request = _make_request(query_string=b"org=org-1")
        assert _resolve_id_source("query:org", request) == "org-1"

    def test_missing_query_raises(self):
        request = _make_request()
        with pytest.raises(ValueError, match="'org'"):
            _resolve_id_source("query:org", request)

    def test_static_resolves(self):
        request = _make_request()
        assert _resolve_id_source("static:global", request) == "global"

    def test_callable_resolves(self):
        request = _make_request(path_params={"doc_id": "doc-1"})
        assert _resolve_id_source(lambda r: r.path_params["doc_id"], request) == "doc-1"

    def test_callable_returning_empty_raises(self):
        request = _make_request()
        with pytest.raises(ValueError, match="callable"):
            _resolve_id_source(lambda r: "", request)

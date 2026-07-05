"""Tests for TopazConfig lifecycle, stale cache safety, and semaphore init."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType

from fastapi_topaz._policy import normalize_hyphens
from fastapi_topaz.cache import DecisionCache
from fastapi_topaz.config import TopazConfig


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

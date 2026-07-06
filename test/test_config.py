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


class TestMutationValidation:
    """policy_groups and default_policy are validated on assignment, not just in __init__."""

    def test_policy_groups_setter_rejects_bad_regex(self):
        from fastapi_topaz import PolicyGroup

        config = _make_config()
        with pytest.raises(ValueError, match="Invalid regex"):
            config.policy_groups = [PolicyGroup("(?P<bad", "test.admin")]

    def test_policy_groups_setter_converts_to_tuple(self):
        from fastapi_topaz import PolicyGroup

        config = _make_config()
        config.policy_groups = [PolicyGroup(r"^/admin/", "test.admin")]
        assert isinstance(config.policy_groups, tuple)
        assert config.policy_groups[0].policy_path == "test.admin"

    def test_default_policy_setter_rejects_empty_string(self):
        config = _make_config()
        with pytest.raises(ValueError, match="default_policy must be a non-empty string"):
            config.default_policy = ""

    def test_default_policy_setter_accepts_none_and_value(self):
        config = _make_config(default_policy="test.defaults.open")
        assert config.default_policy == "test.defaults.open"
        config.default_policy = None
        assert config.default_policy is None


@pytest.mark.asyncio
class TestBatchedRelationChecks:
    """F3: check_relations(batch=True) evaluates all relations in one RPC."""

    def _mock_request(self):
        request = Mock(spec=Request)
        request.path_params = {}
        return request

    def _config_with_mock_wire(self, wire_results, **overrides):
        config = _make_config(**overrides)
        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(return_value=wire_results)
        config._authorizer = mock_authorizer
        return config, mock_authorizer

    async def test_single_decisions_call_for_n_relations(self):
        config, authorizer = self._config_with_mock_wire({"can_read": True, "can_write": False})

        results = await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read", "can_write"],
            batch=True,
        )

        assert results == {"can_read": True, "can_write": False}
        authorizer.decisions.assert_awaited_once()
        kwargs = authorizer.decisions.call_args.kwargs
        assert kwargs["policy_path"] == "test.check"
        assert kwargs["decisions"] == ("can_read", "can_write")
        assert kwargs["resource_context"] == {
            "object_type": "document",
            "object_id": "42",
            "subject_type": "user",
        }
        assert "relation" not in kwargs["resource_context"]
        assert kwargs["timeout"] == 5.0

    async def test_default_remains_fanout(self):
        config, authorizer = self._config_with_mock_wire({"allowed": True})

        await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read", "can_write"],
        )

        assert authorizer.decisions.await_count == 2

    async def test_cache_hits_skip_the_wire(self):
        cache = DecisionCache(ttl_seconds=60)
        await cache.set(
            "user-1",
            "test.check",
            "can_read",
            {"object_type": "document", "object_id": "42", "subject_type": "user"},
            True,
        )
        config, authorizer = self._config_with_mock_wire(
            {"can_write": False}, decision_cache=cache
        )

        results = await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read", "can_write"],
            batch=True,
        )

        assert results == {"can_read": True, "can_write": False}
        authorizer.decisions.assert_awaited_once()
        assert authorizer.decisions.call_args.kwargs["decisions"] == ("can_write",)

    async def test_all_cached_makes_no_wire_call(self):
        cache = DecisionCache(ttl_seconds=60)
        ctx = {"object_type": "document", "object_id": "42", "subject_type": "user"}
        await cache.set("user-1", "test.check", "can_read", ctx, True)
        await cache.set("user-1", "test.check", "can_write", ctx, False)
        config, authorizer = self._config_with_mock_wire({}, decision_cache=cache)

        results = await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read", "can_write"],
            batch=True,
        )

        assert results == {"can_read": True, "can_write": False}
        authorizer.decisions.assert_not_awaited()

    async def test_results_are_cached_individually(self):
        cache = DecisionCache(ttl_seconds=60)
        config, authorizer = self._config_with_mock_wire(
            {"can_read": True, "can_write": False}, decision_cache=cache
        )

        await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read", "can_write"],
            batch=True,
        )
        # Second batch is fully served from cache
        await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read", "can_write"],
            batch=True,
        )

        authorizer.decisions.assert_awaited_once()

    async def test_missing_decision_in_response_defaults_to_denied(self):
        config, _ = self._config_with_mock_wire({"can_read": True})

        results = await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read", "can_delete"],
            batch=True,
        )

        assert results == {"can_read": True, "can_delete": False}

    async def test_breaker_open_uses_per_relation_fallback(self):
        from fastapi_topaz.circuit_breaker import CircuitBreaker, CircuitState

        breaker = CircuitBreaker(failure_threshold=1, fallback="cache_then_deny")
        config, authorizer = self._config_with_mock_wire({}, circuit_breaker=breaker)
        breaker._state = CircuitState.OPEN
        import time as _time

        breaker._open_since = _time.monotonic()

        # Stale cache has can_read=True; can_write falls back to deny
        await config._set_stale_cached(
            "user-1",
            "test.check",
            "can_read",
            {"object_type": "document", "object_id": "42", "subject_type": "user"},
            True,
        )

        results = await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read", "can_write"],
            batch=True,
        )

        assert results == {"can_read": True, "can_write": False}
        authorizer.decisions.assert_not_awaited()

    async def test_wire_failure_uses_fallback_and_records_breaker_failure(self):
        from fastapi_topaz.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=10, fallback="cache_then_deny")
        config = _make_config(circuit_breaker=breaker)
        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(side_effect=ConnectionError("down"))
        config._authorizer = mock_authorizer

        results = await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read"],
            batch=True,
        )

        assert results == {"can_read": False}
        assert breaker._failure_count == 1

    async def test_non_breaker_error_propagates(self):
        config = _make_config()
        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(side_effect=RuntimeError("boom"))
        config._authorizer = mock_authorizer

        with pytest.raises(RuntimeError):
            await config.check_relations(
                self._mock_request(),
                object_type="document",
                object_id="42",
                relations=["can_read"],
                batch=True,
            )

    async def test_batch_emits_one_audit_event_per_relation(self):
        audit = Mock()
        audit.log_decision = AsyncMock()
        config, _ = self._config_with_mock_wire(
            {"can_read": True, "can_write": False}, audit_logger=audit
        )

        await config.check_relations(
            self._mock_request(),
            object_type="document",
            object_id="42",
            relations=["can_read", "can_write"],
            batch=True,
        )

        assert audit.log_decision.await_count == 2
        allowed_values = sorted(
            call.kwargs["allowed"] for call in audit.log_decision.await_args_list
        )
        assert allowed_values == [False, True]
        # Batch context carries no "relation" key, so events are policy-type;
        # the object info is still present in resource_context
        assert all(
            call.kwargs["resource_context"]["object_id"] == "42"
            for call in audit.log_decision.await_args_list
        )

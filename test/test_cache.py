"""Tests for the authorization decision cache."""

import time

import pytest

from fastapi_topaz.cache import DecisionCache, make_decision_key


@pytest.mark.asyncio
class TestCacheBasics:
    """Test basic cache operations."""

    async def test_set_and_get(self):
        """Test setting and retrieving a cached value."""
        cache = DecisionCache(ttl_seconds=60)

        await cache.set("user1", "/admin", "allow", None, True)
        result = await cache.get("user1", "/admin", "allow", None)

        assert result is True

    async def test_get_expired_entry(self):
        """Test that expired entries return None."""
        cache = DecisionCache(ttl_seconds=0.1)

        await cache.set("user1", "/admin", "allow", None, True)
        time.sleep(0.2)
        result = await cache.get("user1", "/admin", "allow", None)

        assert result is None

    async def test_size(self):
        """size() reflects the number of stored entries."""
        cache = DecisionCache(ttl_seconds=60)
        assert cache.size() == 0

        await cache.set("user1", "/admin", "allow", None, True)
        await cache.set("user2", "/admin", "allow", None, False)
        assert cache.size() == 2

        await cache.clear()
        assert cache.size() == 0

    async def test_clear(self):
        """Test clearing the cache."""
        cache = DecisionCache(ttl_seconds=60)

        await cache.set("user1", "/admin", "allow", None, True)
        await cache.set("user2", "/admin", "allow", None, False)

        await cache.clear()

        result1 = await cache.get("user1", "/admin", "allow", None)
        result2 = await cache.get("user2", "/admin", "allow", None)

        assert result1 is None
        assert result2 is None


@pytest.mark.asyncio
class TestLRUEviction:
    """Test LRU eviction behavior (M1 fix)."""

    async def test_accessed_entry_survives_eviction(self):
        """Test that accessed entries survive eviction due to LRU."""
        cache = DecisionCache(ttl_seconds=60, max_size=10)

        # Fill cache to max_size
        for i in range(10):
            await cache.set(f"user{i}", "/admin", "allow", None, True)

        # Access first entry (moves it to end of dict)
        result = await cache.get("user0", "/admin", "allow", None)
        assert result is True

        # Add new entry, triggering eviction of oldest 10% (1 entry)
        # Since user0 was moved to end, it should survive
        await cache.set("user10", "/admin", "allow", None, True)

        # Verify accessed entry survived
        assert await cache.get("user0", "/admin", "allow", None) is True

        # Verify new entry exists
        assert await cache.get("user10", "/admin", "allow", None) is True

        # Verify one of the untouched entries was evicted (user1)
        assert await cache.get("user1", "/admin", "allow", None) is None

    async def test_untouched_entries_evicted_first(self):
        """Test that untouched entries are evicted before accessed ones."""
        cache = DecisionCache(ttl_seconds=60, max_size=10)

        # Fill cache
        for i in range(10):
            await cache.set(f"user{i}", "/admin", "allow", None, True)

        # Access user0 (moves to end)
        await cache.get("user0", "/admin", "allow", None)

        # Add user10, evicting oldest 10% (1 entry)
        await cache.set("user10", "/admin", "allow", None, True)

        # user1 should be evicted (oldest untouched), user0 should survive (was accessed)
        assert await cache.get("user1", "/admin", "allow", None) is None
        assert await cache.get("user0", "/admin", "allow", None) is True


class TestMakeDecisionKey:
    """Shared key helper used by DecisionCache and the config stale cache."""

    def test_same_inputs_same_key(self):
        a = make_decision_key("user1", "app.GET.docs", "allowed", {"id": "1"})
        b = make_decision_key("user1", "app.GET.docs", "allowed", {"id": "1"})
        assert a == b

    def test_different_inputs_different_keys(self):
        a = make_decision_key("user1", "app.GET.docs", "allowed", None)
        b = make_decision_key("user2", "app.GET.docs", "allowed", None)
        assert a != b

    def test_nested_dict_ordering_insensitive(self):
        ctx1 = {"outer": {"a": 1, "b": 2}, "id": "1"}
        ctx2 = {"id": "1", "outer": {"b": 2, "a": 1}}
        a = make_decision_key("user1", "app.GET.docs", "allowed", ctx1)
        b = make_decision_key("user1", "app.GET.docs", "allowed", ctx2)
        assert a == b

    def test_stale_cache_key_uses_helper(self):
        from aserto.client import AuthorizerOptions, Identity, IdentityType

        from fastapi_topaz.config import TopazConfig

        config = TopazConfig(
            authorizer_options=AuthorizerOptions(url="localhost:8282"),
            policy_path_root="test",
            identity_provider=lambda r: Identity(
                type=IdentityType.IDENTITY_TYPE_SUB, value="user-1"
            ),
            policy_instance_name="test",
        )
        assert config._make_stale_cache_key(
            "user1", "app.GET.docs", "allowed", {"id": "1"}
        ) == make_decision_key("user1", "app.GET.docs", "allowed", {"id": "1"})


class DictBackend:
    """Minimal custom CacheBackend used to verify structural conformance."""

    def __init__(self):
        self.store = {}

    async def get(self, identity_value, policy_path, decision, resource_context, **scope):
        key = make_decision_key(identity_value, policy_path, decision, resource_context, **scope)
        return self.store.get(key)

    async def set(self, identity_value, policy_path, decision, resource_context, value, **scope):
        key = make_decision_key(identity_value, policy_path, decision, resource_context, **scope)
        self.store[key] = value

    async def clear(self):
        self.store.clear()

    def size(self):
        return len(self.store)


@pytest.mark.asyncio
class TestCacheBackendProtocol:
    """F4: custom backends plug into TopazConfig via the CacheBackend protocol."""

    def _make_config(self, backend):
        from aserto.client import AuthorizerOptions, Identity, IdentityType

        from fastapi_topaz.config import TopazConfig

        return TopazConfig(
            authorizer_options=AuthorizerOptions(url="localhost:8282"),
            policy_path_root="test",
            identity_provider=lambda r: Identity(
                type=IdentityType.IDENTITY_TYPE_SUB, value="user-1"
            ),
            policy_instance_name="test",
            decision_cache=backend,
        )

    def test_decision_cache_conforms_structurally(self):
        from fastapi_topaz.cache import CacheBackend

        assert isinstance(DecisionCache(), CacheBackend)
        assert isinstance(DictBackend(), CacheBackend)

    async def test_check_decision_uses_custom_backend(self):
        from unittest.mock import AsyncMock, MagicMock, Mock

        backend = DictBackend()
        config = self._make_config(backend)
        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(return_value={"allowed": True})
        config._authorizer = mock_authorizer
        request = MagicMock()
        request.path_params = {}

        # First call misses the backend and hits the wire
        assert await config.check_decision(request, "test.GET.docs", "allowed") is True
        assert mock_authorizer.decisions.await_count == 1
        assert backend.size() == 1

        # Second call is served from the custom backend
        assert await config.check_decision(request, "test.GET.docs", "allowed") is True
        assert mock_authorizer.decisions.await_count == 1


@pytest.mark.asyncio
class TestCacheInvalidation:
    """F5: selective decision invalidation."""

    async def _populated_cache(self):
        cache = DecisionCache(ttl_seconds=60)
        await cache.set("alice", "app.GET.docs", "allowed", {"object_id": "1"}, True)
        await cache.set("alice", "app.PUT.docs", "allowed", {"object_id": "2"}, True)
        await cache.set("bob", "app.GET.docs", "allowed", {"object_id": "1"}, False)
        await cache.set("bob", "app.check", "allowed", None, True)
        return cache

    async def test_invalidate_by_identity(self):
        cache = await self._populated_cache()
        removed = await cache.invalidate(identity_value="alice")
        assert removed == 2
        assert cache.size() == 2
        assert await cache.get("alice", "app.GET.docs", "allowed", {"object_id": "1"}) is None
        assert await cache.get("bob", "app.GET.docs", "allowed", {"object_id": "1"}) is False

    async def test_invalidate_by_policy_path(self):
        cache = await self._populated_cache()
        removed = await cache.invalidate(policy_path="app.GET.docs")
        assert removed == 2
        assert await cache.get("alice", "app.PUT.docs", "allowed", {"object_id": "2"}) is True

    async def test_invalidate_by_object_id(self):
        cache = await self._populated_cache()
        removed = await cache.invalidate(object_id="1")
        assert removed == 2
        assert await cache.get("bob", "app.check", "allowed", None) is True

    async def test_invalidate_combined_criteria_are_anded(self):
        cache = await self._populated_cache()
        removed = await cache.invalidate(identity_value="alice", object_id="1")
        assert removed == 1
        assert await cache.get("alice", "app.PUT.docs", "allowed", {"object_id": "2"}) is True
        assert await cache.get("bob", "app.GET.docs", "allowed", {"object_id": "1"}) is False

    async def test_invalidate_no_match_returns_zero(self):
        cache = await self._populated_cache()
        assert await cache.invalidate(identity_value="carol") == 0
        assert cache.size() == 4

    async def test_invalidate_without_criteria_raises(self):
        cache = await self._populated_cache()
        with pytest.raises(ValueError):
            await cache.invalidate()

    async def test_entry_without_object_id_not_matched_by_object_id(self):
        cache = await self._populated_cache()
        removed = await cache.invalidate(identity_value="bob", object_id="1")
        assert removed == 1
        assert await cache.get("bob", "app.check", "allowed", None) is True


@pytest.mark.asyncio
class TestConfigInvalidateCache:
    """F5: TopazConfig.invalidate_cache delegates and clears the stale cache."""

    def _make_config(self, backend):
        from aserto.client import AuthorizerOptions, Identity, IdentityType

        from fastapi_topaz.config import TopazConfig

        return TopazConfig(
            authorizer_options=AuthorizerOptions(url="localhost:8282"),
            policy_path_root="test",
            identity_provider=lambda r: Identity(
                type=IdentityType.IDENTITY_TYPE_SUB, value="user-1"
            ),
            policy_instance_name="test",
            decision_cache=backend,
        )

    async def test_delegates_to_backend_and_clears_stale_cache(self):
        cache = DecisionCache(ttl_seconds=60)
        await cache.set("alice", "test.GET.docs", "allowed", None, True)
        config = self._make_config(cache)
        config._stale_cache["somekey"] = (True, 0.0)

        removed = await config.invalidate_cache(identity_value="alice")

        assert removed == 1
        assert cache.size() == 0
        assert config._stale_cache == {}

    async def test_backend_without_invalidate_is_skipped(self):
        backend = DictBackend()
        await backend.set("alice", "test.GET.docs", "allowed", None, True)
        config = self._make_config(backend)
        config._stale_cache["somekey"] = (True, 0.0)

        removed = await config.invalidate_cache(identity_value="alice")

        assert removed == 0
        assert backend.size() == 1  # backend untouched
        assert config._stale_cache == {}

    async def test_requires_criterion(self):
        config = self._make_config(DecisionCache())
        with pytest.raises(ValueError):
            await config.invalidate_cache()


class TestDecisionKeyCollisions:
    """Regression: cache keys must not collide across identity types,
    policy instances, or separator-bearing values."""

    def test_separator_in_values_does_not_collide(self):
        a = make_decision_key("a:b", "c", "allowed", None)
        b = make_decision_key("a", "b:c", "allowed", None)
        assert a != b

    def test_identity_type_is_part_of_key(self):
        a = make_decision_key("alice", "p", "allowed", None, identity_type="SUB")
        b = make_decision_key("alice", "p", "allowed", None, identity_type="JWT")
        assert a != b

    def test_policy_instance_is_part_of_key(self):
        a = make_decision_key("alice", "p", "allowed", None, policy_instance="a/a")
        b = make_decision_key("alice", "p", "allowed", None, policy_instance="b/b")
        assert a != b


@pytest.mark.asyncio
class TestSharedCacheScoping:
    """Regression: check_decision scopes cache entries by identity type and
    policy instance, so a shared DecisionCache never serves the wrong grant."""

    def _config(self, cache, identity_type, instance="inst"):
        from unittest.mock import AsyncMock, Mock

        from aserto.client import AuthorizerOptions, Identity

        from fastapi_topaz.config import TopazConfig

        config = TopazConfig(
            authorizer_options=AuthorizerOptions(url="localhost:8282"),
            policy_path_root="app",
            identity_provider=lambda r: Identity(type=identity_type, value="alice"),
            policy_instance_name=instance,
            decision_cache=cache,
        )
        config._authorizer = Mock()
        config._authorizer.decisions = AsyncMock(return_value={"allowed": False})
        return config

    def _request(self):
        from unittest.mock import MagicMock

        request = MagicMock()
        request.path_params = {}
        return request

    async def test_identity_types_with_same_value_miss_each_other(self):
        from aserto.client import IdentityType

        cache = DecisionCache()
        sub = self._config(cache, IdentityType.IDENTITY_TYPE_SUB)
        sub._authorizer.decisions.return_value = {"allowed": True}
        assert await sub.check_decision(self._request(), "app.GET.x", "allowed") is True

        jwt = self._config(cache, IdentityType.IDENTITY_TYPE_JWT)
        assert await jwt.check_decision(self._request(), "app.GET.x", "allowed") is False
        jwt._authorizer.decisions.assert_awaited_once()

    async def test_policy_instances_miss_each_other(self):
        from aserto.client import IdentityType

        cache = DecisionCache()
        first = self._config(cache, IdentityType.IDENTITY_TYPE_SUB, instance="one")
        first._authorizer.decisions.return_value = {"allowed": True}
        assert await first.check_decision(self._request(), "app.GET.x", "allowed") is True

        second = self._config(cache, IdentityType.IDENTITY_TYPE_SUB, instance="two")
        assert await second.check_decision(self._request(), "app.GET.x", "allowed") is False
        second._authorizer.decisions.assert_awaited_once()

    async def test_same_scope_still_hits(self):
        from aserto.client import IdentityType

        cache = DecisionCache()
        first = self._config(cache, IdentityType.IDENTITY_TYPE_SUB)
        first._authorizer.decisions.return_value = {"allowed": True}
        await first.check_decision(self._request(), "app.GET.x", "allowed")

        second = self._config(cache, IdentityType.IDENTITY_TYPE_SUB)
        assert await second.check_decision(self._request(), "app.GET.x", "allowed") is True
        second._authorizer.decisions.assert_not_awaited()


@pytest.mark.asyncio
class TestSmallCacheEviction:
    """Regression: max_size < 10 used to evict 0 entries and grow unbounded."""

    async def test_small_cache_stays_bounded(self):
        cache = DecisionCache(max_size=5)
        for i in range(20):
            await cache.set(f"user{i}", "/p", "allowed", None, True)
        assert cache.size() <= 5

    def test_max_size_below_one_rejected(self):
        with pytest.raises(ValueError, match="max_size"):
            DecisionCache(max_size=0)

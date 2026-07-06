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

    async def get(self, identity_value, policy_path, decision, resource_context):
        return self.store.get(make_decision_key(identity_value, policy_path, decision, resource_context))

    async def set(self, identity_value, policy_path, decision, resource_context, value):
        self.store[make_decision_key(identity_value, policy_path, decision, resource_context)] = value

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

"""Tests for the authorization decision cache."""

import time

import pytest

from fastapi_topaz.cache import DecisionCache


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

"""
In-memory TTL cache for authorization decisions.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field

from aserto.client import ResourceContext

__all__ = ["CacheEntry", "DecisionCache"]


@dataclass
class CacheEntry:
    """A cached authorization decision with expiration."""

    value: bool
    expires_at: float


@dataclass
class DecisionCache:
    """
    Simple in-memory TTL cache for authorization decisions.

    Args:
        ttl_seconds: Time-to-live for cache entries (default: 60 seconds)
        max_size: Maximum number of entries to cache (default: 1000)
    """

    ttl_seconds: float = 60.0
    max_size: int = 1000
    _cache: dict[str, CacheEntry] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _make_key(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
    ) -> str:
        """Create a cache key from authorization parameters."""
        ctx_str = str(sorted(resource_context.items())) if resource_context else ""
        key_data = f"{identity_value}:{policy_path}:{decision}:{ctx_str}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]

    async def get(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
    ) -> bool | None:
        """Get a cached decision, or None if not cached or expired."""
        key = self._make_key(identity_value, policy_path, decision, resource_context)
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._cache[key]
                return None
            # Re-insert to mark as recently used (LRU)
            del self._cache[key]
            self._cache[key] = entry
            return entry.value

    async def set(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
        value: bool,
    ) -> None:
        """Cache a decision."""
        key = self._make_key(identity_value, policy_path, decision, resource_context)
        async with self._lock:
            # Evict oldest entries if cache is full
            if len(self._cache) >= self.max_size:
                # Remove expired entries first
                now = time.monotonic()
                expired = [k for k, v in self._cache.items() if v.expires_at < now]
                for k in expired:
                    del self._cache[k]
                # If still full, remove oldest 10%
                if len(self._cache) >= self.max_size:
                    to_remove = list(self._cache.keys())[: self.max_size // 10]
                    for k in to_remove:
                        del self._cache[k]

            self._cache[key] = CacheEntry(
                value=value,
                expires_at=time.monotonic() + self.ttl_seconds,
            )

    async def clear(self) -> None:
        """Clear all cached entries."""
        async with self._lock:
            self._cache.clear()

"""
In-memory TTL cache for authorization decisions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from aserto.client import ResourceContext

__all__ = ["CacheBackend", "CacheEntry", "DecisionCache", "make_decision_key"]


@runtime_checkable
class CacheBackend(Protocol):
    """Structural interface for pluggable decision cache backends.

    Any object implementing these four methods can be passed as
    ``TopazConfig(decision_cache=...)`` — e.g. a Redis- or memcached-backed
    store. :class:`DecisionCache` is the built-in in-memory implementation.

    Backends may additionally implement
    ``async invalidate(identity_value=None, policy_path=None, object_id=None) -> int``;
    when present, :meth:`TopazConfig.invalidate_cache` delegates to it.
    """

    async def get(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
    ) -> bool | None:
        """Return the cached decision, or None if not cached or expired."""
        ...

    async def set(
        self,
        identity_value: str,
        policy_path: str,
        decision: str,
        resource_context: ResourceContext | None,
        value: bool,
    ) -> None:
        """Cache a decision."""
        ...

    async def clear(self) -> None:
        """Remove all cached entries."""
        ...

    def size(self) -> int:
        """Current number of cached entries."""
        ...


def make_decision_key(
    identity_value: str,
    policy_path: str,
    decision: str,
    resource_context: ResourceContext | None,
) -> str:
    """Create a stable cache key from authorization parameters.

    Nested dicts in the resource context are serialized with sorted keys so
    logically identical contexts always produce the same key.
    """
    ctx_str = json.dumps(resource_context, sort_keys=True, default=str) if resource_context else ""
    key_data = f"{identity_value}:{policy_path}:{decision}:{ctx_str}"
    return hashlib.sha256(key_data.encode()).hexdigest()[:32]


@dataclass
class CacheEntry:
    """A cached authorization decision with expiration.

    Key components (identity, policy path, object ID) are stored alongside
    the value so entries can be matched by :meth:`DecisionCache.invalidate`.
    """

    value: bool
    expires_at: float
    identity_value: str = ""
    policy_path: str = ""
    object_id: str | None = None


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
        return make_decision_key(identity_value, policy_path, decision, resource_context)

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

            object_id = resource_context.get("object_id") if resource_context else None
            self._cache[key] = CacheEntry(
                value=value,
                expires_at=time.monotonic() + self.ttl_seconds,
                identity_value=identity_value,
                policy_path=policy_path,
                object_id=str(object_id) if object_id is not None else None,
            )

    async def invalidate(
        self,
        identity_value: str | None = None,
        policy_path: str | None = None,
        object_id: str | None = None,
    ) -> int:
        """Remove cached decisions matching all provided criteria (AND).

        Args:
            identity_value: Remove entries for this identity
            policy_path: Remove entries for this policy path
            object_id: Remove entries whose resource context had this object_id

        Returns:
            Number of entries removed.

        Raises:
            ValueError: If no criterion is provided (use :meth:`clear` to
                remove everything).
        """
        if identity_value is None and policy_path is None and object_id is None:
            raise ValueError("invalidate() requires at least one criterion; use clear() instead")

        async with self._lock:
            matching = [
                key
                for key, entry in self._cache.items()
                if (identity_value is None or entry.identity_value == identity_value)
                and (policy_path is None or entry.policy_path == policy_path)
                and (object_id is None or entry.object_id == object_id)
            ]
            for key in matching:
                del self._cache[key]
            return len(matching)

    def size(self) -> int:
        """Current number of cached entries (may include expired ones)."""
        return len(self._cache)

    async def clear(self) -> None:
        """Clear all cached entries."""
        async with self._lock:
            self._cache.clear()

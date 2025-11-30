"""
Connection pooling for efficient gRPC connection reuse.

Manages a pool of AuthorizerClient connections to reduce overhead
and improve performance for high-throughput applications.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aserto.client import AuthorizerOptions
    from aserto.client.authorizer.aio import AuthorizerClient

from aserto.client import Identity, IdentityType

logger = logging.getLogger("fastapi_topaz.connection_pool")

__all__ = ["ConnectionPool", "PoolStatus", "PooledConnection"]


class PooledConnection:
    """A pooled connection with metadata."""

    def __init__(self, client: AuthorizerClient):
        self.client = client
        self.created_at = time.monotonic()
        self.last_used_at = time.monotonic()
        self.healthy = True
        self._id = id(self)  # Unique ID for hashing

    def mark_used(self) -> None:
        """Update last_used timestamp."""
        self.last_used_at = time.monotonic()

    @property
    def idle_time(self) -> float:
        """Seconds since last use."""
        return time.monotonic() - self.last_used_at

    def __hash__(self) -> int:
        return self._id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PooledConnection):
            return False
        return self._id == other._id


@dataclass
class PoolStatus:
    """Current status of the connection pool."""

    total: int
    idle: int
    busy: int
    healthy_connections: int
    max_connections: int
    min_connections: int

    @property
    def healthy(self) -> bool:
        """Pool is healthy if we have at least one healthy connection."""
        return self.healthy_connections > 0 or self.total == 0


@dataclass
class ConnectionPool:
    """
    Async connection pool for AuthorizerClient connections.

    Manages a pool of gRPC connections to Topaz, reusing them across
    requests to reduce connection overhead.

    Args:
        min_connections: Minimum connections to keep warm
        max_connections: Maximum connections allowed
        acquire_timeout: Seconds to wait for a connection
        connection_timeout: Seconds to establish a new connection
        max_idle_time: Seconds before closing idle connections
        idle_check_interval: Seconds between idle cleanup runs
        health_check_interval: Seconds between health checks
        health_check_timeout: Seconds for health check to complete
        eager_init: Create min_connections at initialization
        retry_on_failure: Retry failed connection creation
        max_retries: Maximum connection creation retries
    """

    # Pool sizing
    min_connections: int = 2
    max_connections: int = 10

    # Timeouts
    acquire_timeout: float = 5.0
    connection_timeout: float = 10.0

    # Idle management
    max_idle_time: float = 300.0
    idle_check_interval: float = 60.0

    # Health checking
    health_check_interval: float = 30.0
    health_check_timeout: float = 5.0

    # Initialization
    eager_init: bool = False

    # Advanced
    retry_on_failure: bool = True
    max_retries: int = 3

    # Internal state (set after init)
    _authorizer_options: AuthorizerOptions | None = field(default=None, repr=False)
    _idle: asyncio.Queue[PooledConnection] = field(
        default_factory=lambda: asyncio.Queue(), init=False, repr=False
    )
    _semaphore: asyncio.Semaphore | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _connections: set[PooledConnection] = field(
        default_factory=set, init=False, repr=False
    )
    _busy: set[PooledConnection] = field(default_factory=set, init=False, repr=False)
    _initialized: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _cleanup_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    def configure(self, authorizer_options: AuthorizerOptions) -> None:
        """Configure the pool with authorizer options."""
        self._authorizer_options = authorizer_options
        self._semaphore = asyncio.Semaphore(self.max_connections)

    async def initialize(self) -> None:
        """Initialize the pool, optionally creating min_connections."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            if self._semaphore is None:
                self._semaphore = asyncio.Semaphore(self.max_connections)

            if self.eager_init and self._authorizer_options:
                for _ in range(self.min_connections):
                    try:
                        conn = await self._create_connection()
                        await self._idle.put(conn)
                    except Exception as e:
                        logger.warning(f"Failed to create initial connection: {e}")

            # Start background cleanup task
            if self.idle_check_interval > 0:
                self._cleanup_task = asyncio.create_task(self._idle_cleanup_loop())

            self._initialized = True
            logger.info(
                f"Connection pool initialized: min={self.min_connections}, "
                f"max={self.max_connections}"
            )

    async def _create_connection(self) -> PooledConnection:
        """Create a new pooled connection."""
        from aserto.client.authorizer.aio import AuthorizerClient

        if not self._authorizer_options:
            raise RuntimeError("ConnectionPool not configured with authorizer_options")

        # Use anonymous identity for pooled connections - actual identity is set per-request
        placeholder_identity = Identity(type=IdentityType.IDENTITY_TYPE_NONE)
        client = AuthorizerClient(identity=placeholder_identity, options=self._authorizer_options)
        conn = PooledConnection(client=client)
        self._connections.add(conn)
        logger.debug(f"Created new connection, pool size: {len(self._connections)}")
        return conn

    async def acquire(self) -> PooledConnection:
        """
        Acquire a connection from the pool.

        Returns an idle connection if available, creates a new one if under
        max_connections, or waits for one to become available.

        Raises:
            asyncio.TimeoutError: If acquire_timeout is exceeded
        """
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        if not self._initialized:
            await self.initialize()

        assert self._semaphore is not None

        # Wait for a slot (respects max_connections)
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.acquire_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting to acquire connection from pool")
            raise

        # Try to get an idle connection
        try:
            conn = self._idle.get_nowait()
            conn.mark_used()
            self._busy.add(conn)
            logger.debug(f"Acquired idle connection, busy: {len(self._busy)}")
            return conn
        except asyncio.QueueEmpty:
            pass

        # Create a new connection
        try:
            conn = await self._create_connection()
            conn.mark_used()
            self._busy.add(conn)
            logger.debug(f"Created new connection for acquire, busy: {len(self._busy)}")
            return conn
        except Exception:
            # Release semaphore if we failed to create connection
            self._semaphore.release()
            raise

    async def release(self, conn: PooledConnection) -> None:
        """Return a connection to the pool."""
        if conn not in self._busy:
            logger.warning("Attempted to release connection not marked as busy")
            return

        self._busy.discard(conn)

        if conn.healthy and not self._closed:
            conn.mark_used()
            await self._idle.put(conn)
            logger.debug("Released connection back to idle pool")
        else:
            # Remove unhealthy connection
            self._connections.discard(conn)
            logger.debug("Discarded unhealthy connection")

        if self._semaphore:
            self._semaphore.release()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[PooledConnection]:
        """Context manager for acquiring and releasing connections."""
        conn = await self.acquire()
        try:
            yield conn
        finally:
            await self.release(conn)

    async def _idle_cleanup_loop(self) -> None:
        """Background task to clean up idle connections."""
        while not self._closed:
            try:
                await asyncio.sleep(self.idle_check_interval)
                await self._cleanup_idle_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in idle cleanup loop: {e}")

    async def _cleanup_idle_connections(self) -> None:
        """Remove connections that have been idle too long."""
        to_close: list[PooledConnection] = []

        # Check idle connections
        temp_idle: list[PooledConnection] = []
        while True:
            try:
                conn = self._idle.get_nowait()
                if conn.idle_time > self.max_idle_time:
                    # Only close if above min_connections
                    if len(self._connections) - len(to_close) > self.min_connections:
                        to_close.append(conn)
                    else:
                        temp_idle.append(conn)
                else:
                    temp_idle.append(conn)
            except asyncio.QueueEmpty:
                break

        # Put back connections we're keeping
        for conn in temp_idle:
            await self._idle.put(conn)

        # Close stale connections
        for conn in to_close:
            self._connections.discard(conn)
            logger.debug(f"Closed idle connection, pool size: {len(self._connections)}")

    def status(self) -> PoolStatus:
        """Get current pool status for health checks."""
        idle_count = self._idle.qsize()
        busy_count = len(self._busy)
        healthy_count = sum(1 for c in self._connections if c.healthy)

        return PoolStatus(
            total=len(self._connections),
            idle=idle_count,
            busy=busy_count,
            healthy_connections=healthy_count,
            max_connections=self.max_connections,
            min_connections=self.min_connections,
        )

    async def close(self) -> None:
        """Close all connections and shut down the pool."""
        self._closed = True

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Clear idle queue
        while True:
            try:
                self._idle.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Clear all connections
        self._connections.clear()
        self._busy.clear()

        logger.info("Connection pool closed")

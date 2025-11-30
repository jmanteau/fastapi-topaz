"""
Tests for connection pooling.

ConnectionPool manages a pool of reusable authorizer client connections to
reduce connection overhead. Supports min/max connections, health checking,
and idle connection cleanup.

Test organization:
- TestPooledConnection: Individual connection wrapper behavior
- TestPoolStatus: Pool health status reporting
- TestConnectionPool: Core pool operations (acquire, release, close)
- TestConnectionPoolEagerInit: Pre-warming connections at startup
- TestConnectionPoolCleanup: Idle connection eviction
"""
from __future__ import annotations

import asyncio
from unittest.mock import Mock, patch

import pytest
from aserto.client import AuthorizerOptions

from fastapi_topaz.connection_pool import ConnectionPool, PooledConnection, PoolStatus

# Patch target for AuthorizerClient - must match the import path used in connection_pool.py
AUTHORIZER_CLIENT_PATCH = "aserto.client.authorizer.aio.AuthorizerClient"


@pytest.fixture
def authorizer_options():
    return AuthorizerOptions(url="localhost:8282", tenant_id="test", api_key="key")


@pytest.fixture
def pool(authorizer_options):
    p = ConnectionPool(min_connections=1, max_connections=3, acquire_timeout=1.0)
    p.configure(authorizer_options)
    return p


class TestPooledConnection:
    """
    Individual connection wrapper behavior.

    PooledConnection wraps an authorizer client and tracks usage time
    and health status for pool management decisions.
    """

    def test_creation(self):
        mock_client = Mock()
        conn = PooledConnection(client=mock_client)
        assert conn.client == mock_client
        assert conn.healthy is True

    def test_mark_used(self):
        mock_client = Mock()
        conn = PooledConnection(client=mock_client)
        initial_time = conn.last_used_at
        conn.mark_used()
        assert conn.last_used_at >= initial_time

    def test_idle_time(self):
        mock_client = Mock()
        conn = PooledConnection(client=mock_client)
        assert conn.idle_time >= 0


class TestPoolStatus:
    """
    Pool health status reporting.

    PoolStatus provides metrics for monitoring: total/idle/busy counts,
    healthy connection count, and overall pool health determination.
    """

    def test_healthy_when_has_connections(self):
        status = PoolStatus(
            total=5,
            idle=3,
            busy=2,
            healthy_connections=5,
            max_connections=10,
            min_connections=2,
        )
        assert status.healthy is True

    def test_healthy_when_empty(self):
        status = PoolStatus(
            total=0,
            idle=0,
            busy=0,
            healthy_connections=0,
            max_connections=10,
            min_connections=2,
        )
        assert status.healthy is True  # Empty pool is considered healthy

    def test_unhealthy_when_no_healthy_connections(self):
        status = PoolStatus(
            total=5,
            idle=3,
            busy=2,
            healthy_connections=0,
            max_connections=10,
            min_connections=2,
        )
        assert status.healthy is False


class TestConnectionPool:
    """
    Core pool operations: acquire, release, and lifecycle.

    ConnectionPool provides async context manager for safe connection handling.
    Enforces max_connections limit with timeout on acquire when pool is exhausted.
    """

    @pytest.mark.asyncio
    async def test_initialize(self, pool):
        await pool.initialize()
        assert pool._initialized is True

    @pytest.mark.asyncio
    async def test_double_initialize_is_safe(self, pool):
        await pool.initialize()
        await pool.initialize()  # Should not raise
        assert pool._initialized is True

    @pytest.mark.asyncio
    async def test_acquire_creates_connection(self, pool):
        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()
            conn = await pool.acquire()
            assert conn is not None
            assert conn in pool._busy
            await pool.release(conn)

    @pytest.mark.asyncio
    async def test_release_returns_to_idle(self, pool):
        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()
            conn = await pool.acquire()
            await pool.release(conn)
            assert conn not in pool._busy
            assert pool._idle.qsize() == 1

    @pytest.mark.asyncio
    async def test_acquire_reuses_idle_connection(self, pool):
        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()
            conn1 = await pool.acquire()
            await pool.release(conn1)

            conn2 = await pool.acquire()
            assert conn1 is conn2  # Same connection reused
            await pool.release(conn2)

    @pytest.mark.asyncio
    async def test_max_connections_limit(self, pool):
        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()

            # Acquire max connections
            conns = []
            for _ in range(pool.max_connections):
                conns.append(await pool.acquire())

            assert len(pool._busy) == pool.max_connections

            # Next acquire should timeout
            with pytest.raises(asyncio.TimeoutError):
                await pool.acquire()

            # Release all
            for conn in conns:
                await pool.release(conn)

    @pytest.mark.asyncio
    async def test_context_manager(self, pool):
        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()

            async with pool.connection() as conn:
                assert conn in pool._busy

            assert conn not in pool._busy

    @pytest.mark.asyncio
    async def test_status(self, pool):
        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()

            conn = await pool.acquire()
            status = pool.status()

            assert status.total == 1
            assert status.busy == 1
            assert status.idle == 0
            assert status.max_connections == 3
            assert status.min_connections == 1

            await pool.release(conn)

    @pytest.mark.asyncio
    async def test_close(self, pool):
        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()

            conn = await pool.acquire()
            await pool.release(conn)
            await pool.close()

            assert pool._closed is True
            assert len(pool._connections) == 0

    @pytest.mark.asyncio
    async def test_acquire_after_close_raises(self, pool):
        await pool.close()
        with pytest.raises(RuntimeError, match="closed"):
            await pool.acquire()

    @pytest.mark.asyncio
    async def test_unhealthy_connection_not_returned_to_idle(self, pool):
        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()

            conn = await pool.acquire()
            conn.healthy = False
            await pool.release(conn)

            # Connection should be discarded, not in idle
            assert pool._idle.qsize() == 0
            assert conn not in pool._connections


class TestConnectionPoolEagerInit:
    """
    Eager initialization (pre-warming connections).

    With eager_init=True, the pool creates min_connections at startup
    instead of lazily on first acquire. Reduces latency for first requests.
    """

    @pytest.mark.asyncio
    async def test_eager_init_creates_min_connections(self, authorizer_options):
        pool = ConnectionPool(
            min_connections=2,
            max_connections=5,
            eager_init=True,
            idle_check_interval=0,  # Disable cleanup for test
        )
        pool.configure(authorizer_options)

        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()
            await pool.initialize()

            assert pool._idle.qsize() == 2
            assert len(pool._connections) == 2

        await pool.close()


class TestConnectionPoolCleanup:
    """
    Idle connection eviction.

    Connections idle longer than max_idle_time are closed to free resources.
    Cleanup maintains at least min_connections in the pool.
    """

    @pytest.mark.asyncio
    async def test_cleanup_removes_stale_connections(self, authorizer_options):
        pool = ConnectionPool(
            min_connections=1,
            max_connections=5,
            max_idle_time=0.01,  # Very short for testing
            idle_check_interval=0,  # Disable background task
        )
        pool.configure(authorizer_options)

        with patch(AUTHORIZER_CLIENT_PATCH) as mock_client_class:
            mock_client_class.return_value = Mock()

            # Create 3 connections
            conns = [await pool.acquire() for _ in range(3)]
            for c in conns:
                await pool.release(c)

            assert pool._idle.qsize() == 3

            # Wait for idle time to pass
            await asyncio.sleep(0.02)

            # Trigger cleanup
            await pool._cleanup_idle_connections()

            # Should keep min_connections (1), close the rest (2)
            assert pool._idle.qsize() == 1

        await pool.close()

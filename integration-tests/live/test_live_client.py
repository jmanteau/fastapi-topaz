"""Live tests for the shared gRPC channel client (fixes C2 and F1).

Every test here goes over a real TLS gRPC connection to the Topaz container.
Covers real allow/deny decisions, single-channel reuse under sequential and
concurrent load, per-call deadlines, and close/re-dial lifecycle.
"""

from __future__ import annotations

import asyncio

import grpc
import grpc.aio
import pytest
from conftest import AUTH_POLICY


async def test_tls_allow(make_config, make_request):
    config = make_config()
    allowed = await config.is_allowed(make_request("alice"), AUTH_POLICY)
    assert allowed is True


async def test_tls_deny(make_config, make_request):
    config = make_config()
    allowed = await config.is_allowed(make_request(), AUTH_POLICY)
    assert allowed is False


async def test_channel_reuse_across_requests(make_config, make_request, monkeypatch):
    real_secure_channel = grpc.aio.secure_channel
    dials: list[str] = []

    def counting_secure_channel(*args, **kwargs):
        dials.append(kwargs.get("target") or args[0])
        return real_secure_channel(*args, **kwargs)

    monkeypatch.setattr(grpc.aio, "secure_channel", counting_secure_channel)

    config = make_config()
    for _ in range(20):
        assert await config.is_allowed(make_request("alice"), AUTH_POLICY)
    stub_after_sequential = config._authorizer._stub

    results = await asyncio.gather(
        *[config.is_allowed(make_request("alice"), AUTH_POLICY) for _ in range(10)]
    )
    assert all(results)

    assert len(dials) == 1
    assert config._authorizer._stub is stub_after_sequential


async def test_concurrent_first_call_single_channel(make_config, make_request, monkeypatch):
    real_secure_channel = grpc.aio.secure_channel
    dials: list[str] = []

    def counting_secure_channel(*args, **kwargs):
        dials.append(kwargs.get("target") or args[0])
        return real_secure_channel(*args, **kwargs)

    monkeypatch.setattr(grpc.aio, "secure_channel", counting_secure_channel)

    config = make_config()
    results = await asyncio.gather(
        *[config.is_allowed(make_request("alice"), AUTH_POLICY) for _ in range(10)]
    )
    assert all(results)
    assert len(dials) == 1


async def test_deadline_exceeded_raises(make_config, make_request):
    config = make_config(check_timeout=0.000001)
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await config.is_allowed(make_request("alice"), AUTH_POLICY)
    assert exc_info.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED


async def test_close_then_reuse(make_config, make_request):
    config = make_config()
    assert await config.is_allowed(make_request("alice"), AUTH_POLICY)
    assert config._authorizer._channel is not None

    await config.close()
    assert config._authorizer._channel is None
    assert config._authorizer._stub is None

    await config.close()  # second close is a no-op

    # Next call lazily re-dials and succeeds
    assert await config.is_allowed(make_request("alice"), AUTH_POLICY)
    assert config._authorizer._channel is not None


async def test_close_unopened_config(make_config):
    config = make_config()
    await config.close()
    assert config._authorizer._channel is None

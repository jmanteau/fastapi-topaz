"""Tests for the shared-channel authorizer client (C2 + F1 fixes)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType

from fastapi_topaz._client import SharedAuthorizerClient
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


def _mock_request():
    request = MagicMock()
    request.path_params = {}
    return request


class TestSharedClientLifecycle:
    """Channel lifecycle: lazy creation and cleanup on close."""

    def test_construction_creates_no_channel(self):
        """Constructing the client (or a TopazConfig) must not open a channel."""
        client = SharedAuthorizerClient(AuthorizerOptions(url="localhost:8282"))
        assert client._channel is None
        assert client._stub is None

        config = _make_config()
        assert config._authorizer._channel is None

    @pytest.mark.asyncio
    async def test_close_without_channel_is_safe(self):
        client = SharedAuthorizerClient(AuthorizerOptions(url="localhost:8282"))
        await client.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_closes_channel(self):
        client = SharedAuthorizerClient(AuthorizerOptions(url="localhost:8282"))
        mock_channel = Mock()
        mock_channel.close = AsyncMock()
        client._channel = mock_channel
        client._stub = Mock()

        await client.close()

        mock_channel.close.assert_awaited_once()
        assert client._channel is None
        assert client._stub is None

    @pytest.mark.asyncio
    async def test_config_close_closes_shared_client(self):
        """TopazConfig.close() must close the shared authorizer client."""
        config = _make_config()
        mock_authorizer = Mock()
        mock_authorizer.close = AsyncMock()
        config._authorizer = mock_authorizer

        await config.close()

        mock_authorizer.close.assert_awaited_once()


class TestCheckDecisionUsesSharedClient:
    """check_decision routes through the shared client with per-call identity and deadline."""

    @pytest.mark.asyncio
    async def test_passes_timeout_and_identity(self):
        config = _make_config(check_timeout=2.5)
        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(return_value={"allowed": True})
        config._authorizer = mock_authorizer

        result = await config.check_decision(_mock_request(), "test.GET.docs", "allowed")

        assert result is True
        kwargs = mock_authorizer.decisions.call_args.kwargs
        assert kwargs["timeout"] == 2.5
        assert kwargs["identity"].value == "user-1"
        assert kwargs["policy_path"] == "test.GET.docs"

    @pytest.mark.asyncio
    async def test_default_timeout_is_five_seconds(self):
        config = _make_config()
        assert config.check_timeout == 5.0

        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(return_value={"allowed": True})
        config._authorizer = mock_authorizer

        await config.check_decision(_mock_request(), "test.GET.docs", "allowed")
        assert mock_authorizer.decisions.call_args.kwargs["timeout"] == 5.0

    @pytest.mark.asyncio
    async def test_timeout_none_disables_deadline(self):
        config = _make_config(check_timeout=None)
        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(return_value={"allowed": True})
        config._authorizer = mock_authorizer

        await config.check_decision(_mock_request(), "test.GET.docs", "allowed")
        assert mock_authorizer.decisions.call_args.kwargs["timeout"] is None

    @pytest.mark.asyncio
    async def test_no_client_created_per_request(self, monkeypatch):
        """check_decision must not call the deprecated create_client path."""
        config = _make_config()
        mock_authorizer = Mock()
        mock_authorizer.decisions = AsyncMock(return_value={"allowed": True})
        config._authorizer = mock_authorizer

        create_client_calls = [0]

        def counting_create_client(self, request):
            create_client_calls[0] += 1
            return Mock()

        monkeypatch.setattr(TopazConfig, "create_client", counting_create_client)

        await config.check_decision(_mock_request(), "test.GET.docs", "allowed")
        assert create_client_calls[0] == 0


class TestInsecureChannel:
    """F2: first-class insecure (plaintext) channel option for local development."""

    @pytest.mark.asyncio
    async def test_insecure_true_creates_insecure_channel(self, monkeypatch):
        import grpc.aio

        insecure_mock = Mock(return_value=Mock())
        secure_mock = Mock(return_value=Mock())
        monkeypatch.setattr(grpc.aio, "insecure_channel", insecure_mock)
        monkeypatch.setattr(grpc.aio, "secure_channel", secure_mock)

        client = SharedAuthorizerClient(AuthorizerOptions(url="localhost:8282"), insecure=True)
        await client._ensure_channel()

        insecure_mock.assert_called_once_with(target="localhost:8282")
        secure_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_creates_secure_channel(self, monkeypatch):
        import grpc.aio

        insecure_mock = Mock(return_value=Mock())
        secure_mock = Mock(return_value=Mock())
        monkeypatch.setattr(grpc.aio, "insecure_channel", insecure_mock)
        monkeypatch.setattr(grpc.aio, "secure_channel", secure_mock)

        client = SharedAuthorizerClient(AuthorizerOptions(url="localhost:8282"))
        await client._ensure_channel()

        secure_mock.assert_called_once()
        insecure_mock.assert_not_called()

    def test_config_propagates_insecure_flag(self):
        config = _make_config(insecure=True)
        assert config._authorizer._insecure is True

        default_config = _make_config()
        assert default_config._authorizer._insecure is False

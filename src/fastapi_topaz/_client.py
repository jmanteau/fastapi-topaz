"""Internal shared-channel authorizer client.

Unlike ``aserto.client.authorizer.aio.AuthorizerClient`` (which binds identity
at construction time and opens a new gRPC channel per instance), this client
holds a single long-lived channel and takes identity per call, so one instance
can serve every authorization check in the application.
"""

from __future__ import annotations

import asyncio
import typing

import aserto.authorizer.v2 as authorizer
import aserto.authorizer.v2.api as api
import aserto.client.resource_context as res_ctx
import grpc.aio
from aserto.client import AuthorizerOptions, Identity, ResourceContext
from grpc import ssl_channel_credentials

__all__ = ["SharedAuthorizerClient"]


class SharedAuthorizerClient:
    """Authorizer client holding one long-lived gRPC channel.

    The channel is created lazily on the first call so that constructing this
    object (e.g. at import time, before an event loop exists) never touches
    the network or binds to an event loop.
    """

    def __init__(self, options: AuthorizerOptions) -> None:
        self._options = options
        self._channel: grpc.aio.Channel | None = None
        self._stub: typing.Any = None
        self._channel_lock = asyncio.Lock()

    async def _ensure_channel(self) -> typing.Any:
        """Create the channel and stub once, on first use."""
        if self._stub is not None:
            return self._stub
        async with self._channel_lock:
            if self._stub is None:
                self._channel = grpc.aio.secure_channel(
                    target=self._options.url,
                    credentials=ssl_channel_credentials(self._options.cert),
                )
                self._stub = authorizer.AuthorizerStub(self._channel)
        return self._stub

    @property
    def _metadata(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._options.auth_headers.items())

    async def decisions(
        self,
        *,
        identity: Identity,
        policy_path: str,
        decisions: typing.Sequence[str],
        policy_instance_name: str = "",
        policy_instance_label: str = "",
        resource_context: ResourceContext | None = None,
        timeout: float | None = None,
    ) -> dict[str, bool]:
        """Evaluate policy decisions for the given identity.

        Args:
            identity: Identity to evaluate (per call, not bound at construction)
            policy_path: Policy module path to evaluate
            decisions: Decision names to evaluate (e.g. ("allowed",))
            policy_instance_name: Policy instance name
            policy_instance_label: Policy instance label
            resource_context: Optional resource context
            timeout: gRPC deadline in seconds for this call
        """
        stub = await self._ensure_channel()
        response = await stub.Is(
            authorizer.IsRequest(
                policy_context=api.PolicyContext(
                    path=policy_path,
                    decisions=list(decisions),
                ),
                identity_context=api.IdentityContext(
                    identity=identity.value or "",
                    type=identity.type,
                ),
                resource_context=res_ctx.serialize_resource_context(resource_context or {}),
                policy_instance=api.PolicyInstance(
                    name=policy_instance_name,
                    instance_label=policy_instance_label,
                ),
            ),
            metadata=self._metadata,
            timeout=timeout,
        )
        results: dict[str, bool] = {}
        for decision_object in response.decisions:
            results[decision_object.decision] = getattr(decision_object, "is")
        return results

    async def close(self) -> None:
        """Close the underlying channel if it was created."""
        if self._channel is not None:
            await self._channel.close(None)
            self._channel = None
            self._stub = None

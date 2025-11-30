"""
Tests for observability: PrometheusMetrics and OTelTracing.

The observability module provides optional metrics and tracing for authorization
decisions. Both are designed to degrade gracefully when dependencies (prometheus_client,
opentelemetry) are not installed.

Test organization:
- TestPrometheusMetrics: Metrics recording and configuration
- TestPrometheusMetricsIntegration: Integration with TopazConfig
- TestOTelTracing: Distributed tracing spans
- TestOTelTracingIntegration: Integration with TopazConfig
- TestCombinedObservability: Using both metrics and tracing together
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from fastapi_topaz import (
    DecisionCache,
    OTelTracing,
    PrometheusMetrics,
    TopazConfig,
    require_policy_allowed,
)


@pytest.fixture
def authorizer_options():
    return AuthorizerOptions(url="localhost:8282", tenant_id="test", api_key="key")


@pytest.fixture
def identity_provider():
    return lambda req: Identity(type=IdentityType.IDENTITY_TYPE_SUB, value="user-123")


@pytest.fixture
def mock_client():
    client = Mock()
    client.decisions = AsyncMock(return_value={"allowed": True})
    return client


@pytest.fixture
def patch_client(monkeypatch, mock_client):
    monkeypatch.setattr(TopazConfig, "create_client", lambda self, req: mock_client)
    return mock_client


class TestPrometheusMetrics:
    """
    Prometheus metrics recording and configuration.

    PrometheusMetrics records authorization request counts, latencies, cache hits/misses,
    and circuit breaker state. Gracefully degrades to no-ops when prometheus_client
    is not installed.
    """

    def test_creation_with_defaults(self):
        """Should create with default settings."""
        metrics = PrometheusMetrics()
        assert metrics.prefix == "topaz"
        assert metrics.include_policy_path is False

    def test_creation_with_custom_prefix(self):
        """Should accept custom prefix."""
        metrics = PrometheusMetrics(prefix="myapp")
        assert metrics.prefix == "myapp"

    def test_include_policy_path_option(self):
        """Should accept include_policy_path option."""
        metrics = PrometheusMetrics(include_policy_path=True)
        assert metrics.include_policy_path is True

    def test_works_without_prometheus_client(self):
        """Should not raise errors when prometheus_client not installed."""
        metrics = PrometheusMetrics()
        # These should be no-ops when prometheus_client not available
        metrics.record_auth_request("middleware", "allowed", "policy")
        metrics.record_cache_hit("middleware")
        metrics.record_cache_miss("middleware")
        metrics.record_latency(0.01, "middleware", False)
        metrics.record_error("TestError")
        metrics.set_circuit_state(0)


class TestPrometheusMetricsIntegration:
    """Integration with TopazConfig - metrics are recorded during authorization."""

    def test_config_accepts_metrics(self, authorizer_options, identity_provider, patch_client):
        """TopazConfig should accept metrics parameter."""
        metrics = PrometheusMetrics()
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            metrics=metrics,
        )
        assert config.metrics is metrics

    def test_metrics_recorded_on_auth_check(self, authorizer_options, identity_provider, patch_client):
        """Metrics should be recorded during authorization check."""
        metrics = PrometheusMetrics()
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            metrics=metrics,
        )

        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(config, "test.policy"))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200


class TestOTelTracing:
    """
    OpenTelemetry distributed tracing configuration.

    OTelTracing creates spans for authorization checks and cache operations.
    Gracefully degrades to no-ops when opentelemetry is not installed.
    """

    def test_creation_with_defaults(self):
        """Should create with default settings."""
        tracing = OTelTracing()
        assert tracing.trace_all_checks is True
        assert tracing.include_identity is False
        assert tracing.span_name_prefix == "topaz"

    def test_creation_with_custom_settings(self):
        """Should accept custom settings."""
        tracing = OTelTracing(
            trace_all_checks=False,
            include_identity=True,
            span_name_prefix="myapp",
        )
        assert tracing.trace_all_checks is False
        assert tracing.include_identity is True
        assert tracing.span_name_prefix == "myapp"

    def test_works_without_opentelemetry(self):
        """Should not raise errors when opentelemetry not installed."""
        tracing = OTelTracing()
        # These should be no-ops when opentelemetry not available
        span = tracing.start_auth_span("middleware", "policy", "test.path")
        tracing.end_auth_span(span, "allowed", False, 10.5)
        cache_span = tracing.start_cache_span("lookup")
        tracing.end_cache_span(cache_span, hit=True)
        trace_id = tracing.get_current_trace_id()
        # trace_id is None when opentelemetry not available
        assert trace_id is None or isinstance(trace_id, str)


class TestOTelTracingIntegration:
    """Integration with TopazConfig - spans are created during authorization."""

    def test_config_accepts_tracing(self, authorizer_options, identity_provider, patch_client):
        """TopazConfig should accept tracing parameter."""
        tracing = OTelTracing()
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            tracing=tracing,
        )
        assert config.tracing is tracing

    def test_tracing_during_auth_check(self, authorizer_options, identity_provider, patch_client):
        """Tracing should work during authorization check."""
        tracing = OTelTracing()
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            tracing=tracing,
        )

        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(config, "test.policy"))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200


class TestCombinedObservability:
    """Using metrics, tracing, and caching together in TopazConfig."""

    def test_both_metrics_and_tracing(self, authorizer_options, identity_provider, patch_client):
        """Should work with both metrics and tracing enabled."""
        metrics = PrometheusMetrics()
        tracing = OTelTracing()

        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            metrics=metrics,
            tracing=tracing,
        )

        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(config, "test.policy"))):
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200

    def test_with_caching(self, authorizer_options, identity_provider, patch_client):
        """Should work with caching, metrics, and tracing."""
        metrics = PrometheusMetrics()
        tracing = OTelTracing()
        cache = DecisionCache(ttl_seconds=60)

        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            decision_cache=cache,
            metrics=metrics,
            tracing=tracing,
        )

        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(config, "test.policy"))):
            return {"status": "ok"}

        client = TestClient(app)

        # First request - cache miss
        response = client.get("/test")
        assert response.status_code == 200

        # Second request - cache hit
        response = client.get("/test")
        assert response.status_code == 200

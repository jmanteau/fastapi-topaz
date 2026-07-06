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
from fastapi_topaz._client import SharedAuthorizerClient


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
    monkeypatch.setattr(SharedAuthorizerClient, "decisions", mock_client.decisions)
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

    def test_duplicate_instances_do_not_raise(self):
        """Regression (B7): two instances sharing the global registry reuse
        existing collectors instead of raising 'Duplicated timeseries'."""
        first = PrometheusMetrics(prefix="dup_test")
        second = PrometheusMetrics(prefix="dup_test")
        first.record_auth_request("middleware", "allowed", "policy")
        second.record_auth_request("middleware", "allowed", "policy")
        first.record_latency(0.01, "middleware", False)
        second.record_latency(0.02, "middleware", False)
        second.set_circuit_state(1)

    def test_metrics_increment_with_real_collectors(self):
        """With prometheus_client installed, counters actually increment."""
        prometheus_client = pytest.importorskip("prometheus_client")
        registry = prometheus_client.CollectorRegistry()
        metrics = PrometheusMetrics(prefix="real_test", registry=registry)

        metrics.record_auth_request("middleware", "allowed", "policy")
        metrics.record_auth_request("middleware", "allowed", "policy")
        metrics.record_cache_hit("dependency")
        metrics.set_cache_size(42)

        assert (
            registry.get_sample_value(
                "real_test_auth_requests_total",
                {"source": "middleware", "decision": "allowed", "check_type": "policy"},
            )
            == 2
        )
        assert (
            registry.get_sample_value("real_test_cache_hits_total", {"source": "dependency"}) == 1
        )
        assert registry.get_sample_value("real_test_cache_size") == 42

    def test_duplicate_instances_share_collectors(self):
        """Both instances record into the same underlying collector."""
        prometheus_client = pytest.importorskip("prometheus_client")
        registry = prometheus_client.CollectorRegistry()
        first = PrometheusMetrics(prefix="shared_test", registry=registry)
        second = PrometheusMetrics(prefix="shared_test", registry=registry)

        first.record_cache_hit("middleware")
        second.record_cache_hit("middleware")

        assert (
            registry.get_sample_value("shared_test_cache_hits_total", {"source": "middleware"}) == 2
        )


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

    def test_metrics_recorded_on_auth_check(
        self, authorizer_options, identity_provider, patch_client
    ):
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


@pytest.fixture
def span_exporter():
    """OTelTracing wired to an in-memory exporter, plus the exporter itself."""
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def _make_tracing(provider, **kwargs):
    tracing = OTelTracing(**kwargs)
    tracing._tracer = provider.get_tracer("fastapi_topaz")
    return tracing


class TestOTelTracingSpans:
    """Real span content verified with the OTel SDK in-memory exporter."""

    def test_auth_span_attributes(self, span_exporter):
        provider, exporter = span_exporter
        tracing = _make_tracing(provider)

        span = tracing.start_auth_span("middleware", "policy", "test.GET.docs", "user-1")
        tracing.end_auth_span(span, decision="allowed", cached=True, latency_ms=12.5)

        finished = exporter.get_finished_spans()
        assert len(finished) == 1
        exported = finished[0]
        assert exported.name == "topaz.authorization"
        attrs = dict(exported.attributes)
        assert attrs["topaz.source"] == "middleware"
        assert attrs["topaz.check_type"] == "policy"
        assert attrs["topaz.decision"] == "allowed"
        assert attrs["topaz.cached"] is True
        assert attrs["topaz.latency_ms"] == 12.5
        assert attrs["topaz.denied"] is False
        # Privacy-sensitive attributes are off by default
        assert "topaz.identity" not in attrs
        assert "topaz.policy_path" not in attrs
        assert "topaz.resource_context" not in attrs

    def test_privacy_flags_add_attributes(self, span_exporter):
        provider, exporter = span_exporter
        tracing = _make_tracing(
            provider,
            include_identity=True,
            include_policy_path=True,
            include_resource_context=True,
        )

        span = tracing.start_auth_span("dependency", "rebac", "test.check", "user-1")
        tracing.end_auth_span(
            span,
            decision="denied",
            cached=False,
            latency_ms=3.0,
            resource_context={"object_id": "42"},
        )

        attrs = dict(exporter.get_finished_spans()[0].attributes)
        assert attrs["topaz.identity"] == "user-1"
        assert attrs["topaz.policy_path"] == "test.check"
        assert attrs["topaz.resource_context"] == "{'object_id': '42'}"
        assert attrs["topaz.denied"] is True

    def test_trace_all_checks_false_disables_spans(self, span_exporter):
        provider, exporter = span_exporter
        tracing = _make_tracing(provider, trace_all_checks=False)

        assert tracing.start_auth_span("middleware", "policy") is None
        assert tracing.start_topaz_span() is None
        assert exporter.get_finished_spans() == ()

    def test_custom_span_name_prefix(self, span_exporter):
        provider, exporter = span_exporter
        tracing = _make_tracing(provider, span_name_prefix="myapp")

        span = tracing.start_auth_span("manual", "policy")
        tracing.end_auth_span(span, decision="allowed", cached=False, latency_ms=1.0)

        exported = exporter.get_finished_spans()[0]
        assert exported.name == "myapp.authorization"
        assert dict(exported.attributes)["myapp.source"] == "manual"

    def test_record_error_sets_error_status(self, span_exporter):
        from opentelemetry.trace import StatusCode

        provider, exporter = span_exporter
        tracing = _make_tracing(provider)

        span = tracing.start_auth_span("middleware", "policy")
        tracing.record_error(span, ConnectionError("topaz down"))

        exported = exporter.get_finished_spans()[0]
        assert exported.status.status_code == StatusCode.ERROR
        assert "topaz down" in exported.status.description
        assert exported.events[0].name == "exception"

    def test_cache_span_records_hit(self, span_exporter):
        provider, exporter = span_exporter
        tracing = _make_tracing(provider)

        span = tracing.start_cache_span("lookup")
        tracing.end_cache_span(span, hit=True)

        exported = exporter.get_finished_spans()[0]
        assert exported.name == "topaz.cache.lookup"
        assert dict(exported.attributes)["hit"] is True

    def test_cache_span_disabled(self, span_exporter):
        provider, exporter = span_exporter
        tracing = _make_tracing(provider, trace_cache_operations=False)

        assert tracing.start_cache_span("lookup") is None
        assert exporter.get_finished_spans() == ()

    def test_topaz_span_records_latency(self, span_exporter):
        provider, exporter = span_exporter
        tracing = _make_tracing(provider)

        span = tracing.start_topaz_span()
        tracing.end_topaz_span(span, latency_ms=42.0)

        exported = exporter.get_finished_spans()[0]
        assert exported.name == "topaz.topaz.request"
        assert dict(exported.attributes)["latency_ms"] == 42.0

    def test_end_helpers_are_noops_for_none_span(self, span_exporter):
        provider, exporter = span_exporter
        tracing = _make_tracing(provider)

        tracing.end_auth_span(None, decision="allowed", cached=False, latency_ms=1.0)
        tracing.end_cache_span(None, hit=True)
        tracing.end_topaz_span(None, latency_ms=1.0)
        tracing.record_error(None, RuntimeError("x"))
        assert exporter.get_finished_spans() == ()

    def test_get_current_trace_id(self, span_exporter):
        from opentelemetry import trace as otel_trace

        provider, exporter = span_exporter
        tracing = _make_tracing(provider)

        assert tracing.get_current_trace_id() is None

        tracer = provider.get_tracer("test")
        with otel_trace.use_span(tracer.start_span("outer"), end_on_exit=True):
            trace_id = tracing.get_current_trace_id()
            assert isinstance(trace_id, str)
            assert len(trace_id) == 32
            assert trace_id != "0" * 32


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

    def test_cache_hit_records_actual_decision(
        self, authorizer_options, identity_provider, patch_client
    ):
        """Regression (B1): cache hits must record the cached decision, not "denied"."""
        metrics = Mock()
        config = TopazConfig(
            authorizer_options=authorizer_options,
            policy_path_root="testapp",
            identity_provider=identity_provider,
            policy_instance_name="test",
            decision_cache=DecisionCache(ttl_seconds=60),
            metrics=metrics,
        )

        app = FastAPI()

        @app.get("/test")
        def route(request: Request, _=Depends(require_policy_allowed(config, "test.policy"))):
            return {"status": "ok"}

        client = TestClient(app)

        # First request populates the cache
        assert client.get("/test").status_code == 200
        # Second request is served from cache
        assert client.get("/test").status_code == 200

        metrics.record_cache_hit.assert_called_once()
        cached_call = metrics.record_auth_request.call_args_list[-1]
        assert cached_call.kwargs["decision"] == "allowed"

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


class TestPrometheusMetricsCoverage:
    """Label branches, circuit counters, and degradation guards."""

    def test_include_policy_path_adds_label(self):
        prometheus_client = pytest.importorskip("prometheus_client")
        registry = prometheus_client.CollectorRegistry()
        metrics = PrometheusMetrics(
            prefix="labeled_test", registry=registry, include_policy_path=True
        )

        metrics.record_auth_request("middleware", "allowed", "policy", policy_path="app.GET.docs")
        metrics.record_latency(0.01, "middleware", False, policy_path="app.GET.docs")

        assert (
            registry.get_sample_value(
                "labeled_test_auth_requests_total",
                {
                    "source": "middleware",
                    "decision": "allowed",
                    "check_type": "policy",
                    "policy_path": "app.GET.docs",
                },
            )
            == 1
        )
        assert (
            registry.get_sample_value(
                "labeled_test_auth_latency_seconds_count",
                {"source": "middleware", "cached": "false", "policy_path": "app.GET.docs"},
            )
            == 1
        )

    def test_circuit_transition_fallback_and_error_counters(self):
        prometheus_client = pytest.importorskip("prometheus_client")
        registry = prometheus_client.CollectorRegistry()
        metrics = PrometheusMetrics(prefix="circuit_test", registry=registry)

        metrics.record_circuit_transition("closed", "open")
        metrics.record_fallback("circuit_open", True, "allowed")
        metrics.record_error("AioRpcError")
        metrics.record_topaz_latency(0.02)
        metrics.record_cache_miss("middleware")

        assert (
            registry.get_sample_value(
                "circuit_test_circuit_transitions_total",
                {"from_state": "closed", "to_state": "open"},
            )
            == 1
        )
        assert (
            registry.get_sample_value(
                "circuit_test_fallback_total",
                {"strategy": "circuit_open", "cache_hit": "true", "decision": "allowed"},
            )
            == 1
        )
        assert (
            registry.get_sample_value(
                "circuit_test_errors_total", {"error_type": "AioRpcError"}
            )
            == 1
        )
        assert (
            registry.get_sample_value(
                "circuit_test_cache_misses_total", {"source": "middleware"}
            )
            == 1
        )

    def test_all_recorders_are_noops_when_prometheus_unavailable(self, monkeypatch):
        """Every record method returns early when prometheus_client is absent."""
        import fastapi_topaz.observability as obs

        monkeypatch.setattr(obs, "PROMETHEUS_AVAILABLE", False)
        metrics = PrometheusMetrics(prefix="noop_test")

        metrics.record_auth_request("middleware", "allowed", "policy")
        metrics.record_cache_hit("middleware")
        metrics.record_cache_miss("middleware")
        metrics.record_latency(0.01, "middleware", False)
        metrics.record_topaz_latency(0.01)
        metrics.record_error("X")
        metrics.set_circuit_state(1)
        metrics.record_circuit_transition("closed", "open")
        metrics.record_fallback("circuit_open", False, "denied")
        metrics.set_cache_size(1)

        assert metrics._initialized is False


class TestOTelTracingCoverage:
    """Tracer/trace-id edge cases."""

    def test_get_tracer_none_when_otel_unavailable(self, monkeypatch):
        import fastapi_topaz.observability as obs

        monkeypatch.setattr(obs, "OTEL_AVAILABLE", False)
        tracing = OTelTracing()
        assert tracing._get_tracer() is None
        assert tracing.get_current_trace_id() is None

    def test_trace_id_none_without_active_span(self):
        pytest.importorskip("opentelemetry")
        tracing = OTelTracing()
        # No active span in this context: the invalid default span yields None
        assert tracing.get_current_trace_id() is None

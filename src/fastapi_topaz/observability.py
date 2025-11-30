"""
Observability: Metrics & Tracing for authorization.

Optional integrations for monitoring authorization performance.
Zero overhead when not configured.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fastapi_topaz.observability")

__all__ = ["PrometheusMetrics", "OTelTracing"]

# Try to import prometheus_client (optional)
try:
    from prometheus_client import REGISTRY, Counter, Gauge, Histogram  # type: ignore[import-not-found]
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    REGISTRY = None

# Try to import opentelemetry (optional)
try:
    from opentelemetry import trace  # type: ignore[import-not-found]
    from opentelemetry.trace import Status, StatusCode  # type: ignore[import-not-found]
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None


@dataclass
class PrometheusMetrics:
    """
    Prometheus metrics collector for authorization decisions.

    Args:
        prefix: Metric name prefix (default: "topaz")
        include_policy_path: Add policy_path label (high cardinality)
        include_object_type: Add object_type label (medium cardinality)
        include_relation: Add relation label (medium cardinality)
        latency_buckets: Histogram buckets for latency
        registry: Custom prometheus registry (default: global)
    """

    prefix: str = "topaz"
    include_policy_path: bool = False
    include_object_type: bool = False
    include_relation: bool = False
    latency_buckets: list[float] = field(
        default_factory=lambda: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
    )
    registry: Any = None

    _initialized: bool = field(default=False, init=False, repr=False)
    _auth_requests: Any = field(default=None, init=False, repr=False)
    _cache_hits: Any = field(default=None, init=False, repr=False)
    _cache_misses: Any = field(default=None, init=False, repr=False)
    _auth_latency: Any = field(default=None, init=False, repr=False)
    _topaz_latency: Any = field(default=None, init=False, repr=False)
    _errors: Any = field(default=None, init=False, repr=False)
    _circuit_state: Any = field(default=None, init=False, repr=False)
    _circuit_transitions: Any = field(default=None, init=False, repr=False)
    _fallback: Any = field(default=None, init=False, repr=False)
    _cache_size: Any = field(default=None, init=False, repr=False)

    def _initialize(self) -> None:
        """Lazy initialization of metrics."""
        if self._initialized or not PROMETHEUS_AVAILABLE:
            return

        registry = self.registry or REGISTRY
        p = self.prefix

        # Build label sets
        base_labels = ["source", "decision", "check_type"]
        if self.include_policy_path:
            base_labels.append("policy_path")

        latency_labels = ["source", "cached"]
        if self.include_policy_path:
            latency_labels.append("policy_path")

        # Counters
        self._auth_requests = Counter(
            f"{p}_auth_requests_total",
            "Total authorization requests",
            base_labels,
            registry=registry,
        )
        self._cache_hits = Counter(
            f"{p}_cache_hits_total",
            "Cache hits",
            ["source"],
            registry=registry,
        )
        self._cache_misses = Counter(
            f"{p}_cache_misses_total",
            "Cache misses",
            ["source"],
            registry=registry,
        )
        self._errors = Counter(
            f"{p}_errors_total",
            "Authorization errors",
            ["error_type"],
            registry=registry,
        )
        self._circuit_transitions = Counter(
            f"{p}_circuit_transitions_total",
            "Circuit state transitions",
            ["from_state", "to_state"],
            registry=registry,
        )
        self._fallback = Counter(
            f"{p}_fallback_total",
            "Circuit breaker fallbacks",
            ["strategy", "cache_hit", "decision"],
            registry=registry,
        )

        # Gauges
        self._circuit_state = Gauge(
            f"{p}_circuit_state",
            "Current circuit state (0=closed, 1=open, 2=half_open)",
            registry=registry,
        )
        self._cache_size = Gauge(
            f"{p}_cache_size",
            "Current number of cached decisions",
            registry=registry,
        )

        # Histograms
        self._auth_latency = Histogram(
            f"{p}_auth_latency_seconds",
            "End-to-end authorization latency",
            latency_labels,
            buckets=self.latency_buckets,
            registry=registry,
        )
        self._topaz_latency = Histogram(
            f"{p}_topaz_latency_seconds",
            "Actual Topaz call latency",
            registry=registry,
            buckets=self.latency_buckets,
        )

        self._initialized = True

    def record_auth_request(
        self,
        source: str,
        decision: str,
        check_type: str,
        policy_path: str | None = None,
    ) -> None:
        """Record an authorization request."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._auth_requests:
            return

        labels = {"source": source, "decision": decision, "check_type": check_type}
        if self.include_policy_path and policy_path:
            labels["policy_path"] = policy_path

        self._auth_requests.labels(**labels).inc()

    def record_cache_hit(self, source: str) -> None:
        """Record a cache hit."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._cache_hits:
            return
        self._cache_hits.labels(source=source).inc()

    def record_cache_miss(self, source: str) -> None:
        """Record a cache miss."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._cache_misses:
            return
        self._cache_misses.labels(source=source).inc()

    def record_latency(
        self,
        latency_seconds: float,
        source: str,
        cached: bool,
        policy_path: str | None = None,
    ) -> None:
        """Record authorization latency."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._auth_latency:
            return

        labels = {"source": source, "cached": str(cached).lower()}
        if self.include_policy_path and policy_path:
            labels["policy_path"] = policy_path

        self._auth_latency.labels(**labels).observe(latency_seconds)

    def record_topaz_latency(self, latency_seconds: float) -> None:
        """Record actual Topaz call latency."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._topaz_latency:
            return
        self._topaz_latency.observe(latency_seconds)

    def record_error(self, error_type: str) -> None:
        """Record an authorization error."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._errors:
            return
        self._errors.labels(error_type=error_type).inc()

    def set_circuit_state(self, state: int) -> None:
        """Set circuit breaker state (0=closed, 1=open, 2=half_open)."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._circuit_state:
            return
        self._circuit_state.set(state)

    def record_circuit_transition(self, from_state: str, to_state: str) -> None:
        """Record circuit state transition."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._circuit_transitions:
            return
        self._circuit_transitions.labels(from_state=from_state, to_state=to_state).inc()

    def record_fallback(self, strategy: str, cache_hit: bool, decision: str) -> None:
        """Record circuit breaker fallback."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._fallback:
            return
        self._fallback.labels(
            strategy=strategy,
            cache_hit=str(cache_hit).lower(),
            decision=decision,
        ).inc()

    def set_cache_size(self, size: int) -> None:
        """Set current cache size."""
        self._initialize()
        if not PROMETHEUS_AVAILABLE or not self._cache_size:
            return
        self._cache_size.set(size)


@dataclass
class OTelTracing:
    """
    OpenTelemetry tracing for authorization decisions.

    Args:
        trace_all_checks: Trace all authorization checks
        trace_cache_operations: Include cache lookup/store spans
        include_identity: Add identity to span attributes (privacy risk)
        include_policy_path: Add policy_path to spans
        include_resource_context: Add full resource context (privacy risk)
        span_name_prefix: Prefix for span names
    """

    trace_all_checks: bool = True
    trace_cache_operations: bool = True
    include_identity: bool = False
    include_policy_path: bool = False
    include_resource_context: bool = False
    span_name_prefix: str = "topaz"

    _tracer: Any = field(default=None, init=False, repr=False)

    def _get_tracer(self) -> Any:
        """Get or create tracer."""
        if not OTEL_AVAILABLE:
            return None
        if self._tracer is None:
            self._tracer = trace.get_tracer("fastapi_topaz")  # type: ignore[union-attr]
        return self._tracer

    def start_auth_span(
        self,
        source: str,
        check_type: str,
        policy_path: str | None = None,
        identity_value: str | None = None,
    ) -> Any:
        """Start an authorization span."""
        tracer = self._get_tracer()
        if not tracer or not self.trace_all_checks:
            return None

        attributes = {
            f"{self.span_name_prefix}.source": source,
            f"{self.span_name_prefix}.check_type": check_type,
        }

        if self.include_policy_path and policy_path:
            attributes[f"{self.span_name_prefix}.policy_path"] = policy_path

        if self.include_identity and identity_value:
            attributes[f"{self.span_name_prefix}.identity"] = identity_value

        return tracer.start_span(
            f"{self.span_name_prefix}.authorization",
            attributes=attributes,
        )

    def end_auth_span(
        self,
        span: Any,
        decision: str,
        cached: bool,
        latency_ms: float,
        resource_context: dict | None = None,
    ) -> None:
        """End an authorization span with results."""
        if not span or not OTEL_AVAILABLE:
            return

        span.set_attribute(f"{self.span_name_prefix}.decision", decision)
        span.set_attribute(f"{self.span_name_prefix}.cached", cached)
        span.set_attribute(f"{self.span_name_prefix}.latency_ms", latency_ms)

        if self.include_resource_context and resource_context:
            span.set_attribute(
                f"{self.span_name_prefix}.resource_context",
                str(resource_context),
            )

        if decision == "denied":
            span.set_status(Status(StatusCode.OK))
        else:
            span.set_status(Status(StatusCode.OK))

        span.end()

    def start_cache_span(self, operation: str) -> Any:
        """Start a cache operation span."""
        tracer = self._get_tracer()
        if not tracer or not self.trace_cache_operations:
            return None

        return tracer.start_span(f"{self.span_name_prefix}.cache.{operation}")

    def end_cache_span(self, span: Any, hit: bool | None = None) -> None:
        """End a cache operation span."""
        if not span or not OTEL_AVAILABLE:
            return

        if hit is not None:
            span.set_attribute("hit", hit)

        span.set_status(Status(StatusCode.OK))
        span.end()

    def start_topaz_span(self) -> Any:
        """Start a Topaz request span."""
        tracer = self._get_tracer()
        if not tracer or not self.trace_all_checks:
            return None

        return tracer.start_span(f"{self.span_name_prefix}.topaz.request")

    def end_topaz_span(self, span: Any, latency_ms: float) -> None:
        """End a Topaz request span."""
        if not span or not OTEL_AVAILABLE:
            return

        span.set_attribute("latency_ms", latency_ms)
        span.set_status(Status(StatusCode.OK))
        span.end()

    def record_error(self, span: Any, error: Exception) -> None:
        """Record an error on a span."""
        if not span or not OTEL_AVAILABLE:
            return

        span.set_status(Status(StatusCode.ERROR, str(error)))
        span.record_exception(error)
        span.end()

    def get_current_trace_id(self) -> str | None:
        """Get current trace ID for correlation."""
        if not OTEL_AVAILABLE:
            return None

        span = trace.get_current_span()  # type: ignore[union-attr]
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().trace_id, "032x")
        return None

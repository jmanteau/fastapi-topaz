# How to Configure Circuit Breaker

Graceful degradation when Topaz is unavailable using cache-aware fallback.

## Basic Configuration

```python
from fastapi_topaz import TopazConfig, CircuitBreaker, DecisionCache

config = TopazConfig(
    authorizer_options=AuthorizerOptions(url="localhost:8282"),
    policy_path_root="myapp",
    identity_provider=get_identity,
    policy_instance_name="myapp",

    decision_cache=DecisionCache(
        ttl_seconds=60,
        max_size=1000,
    ),

    circuit_breaker=CircuitBreaker(
        failure_threshold=5,
        success_threshold=2,
        recovery_timeout=30,
        fallback="cache_then_deny",
        serve_stale_cache=True,
        stale_cache_ttl=300,
    ),
)
```

## Circuit States

| State | Behavior |
|-------|----------|
| CLOSED | Normal operation. Requests go to Topaz. Failures tracked. |
| OPEN | Topaz bypassed. Fallback strategy used. Timer running. |
| HALF-OPEN | Test request sent to Topaz. Success closes, failure reopens. |

## Fallback Strategies

### cache_then_deny (Recommended)

```python
circuit_breaker=CircuitBreaker(fallback="cache_then_deny")
```

Uses cached decision if available, denies if not. Best for security-sensitive applications.

### cache_then_allow

```python
circuit_breaker=CircuitBreaker(fallback="cache_then_allow")
```

Uses cached decision if available, allows if not. Best for availability-critical applications.

### deny

```python
circuit_breaker=CircuitBreaker(fallback="deny")
```

All requests denied when circuit is open. Ignores cache. For high-security systems.

### allow

```python
circuit_breaker=CircuitBreaker(fallback="allow")
```

All requests allowed when circuit is open. Not recommended for production.

### Custom Fallback

```python
async def custom_fallback(
    request: Request,
    policy_path: str,
    resource_context: dict,
    cached_decision: bool | None,
    error: Exception,
) -> bool:
    if cached_decision is not None:
        return cached_decision
    # Allow reads, deny writes
    return request.method in ["GET", "HEAD", "OPTIONS"]

circuit_breaker=CircuitBreaker(fallback=custom_fallback)
```

## Health Check Integration

```python
@app.get("/health")
async def health():
    circuit_status = config.circuit_breaker.status()

    return {
        "status": "degraded" if circuit_status.is_open else "ok",
        "topaz": {
            "circuit_state": circuit_status.state,
            "consecutive_failures": circuit_status.failure_count,
            "last_failure": circuit_status.last_failure_time,
        },
    }
```

## Configuration Reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| failure_threshold | int | 5 | Failures before opening |
| success_threshold | int | 2 | Successes before closing |
| recovery_timeout | float | 30.0 | Seconds before half-open |
| fallback | str/Callable | "cache_then_deny" | Fallback strategy |
| serve_stale_cache | bool | True | Serve expired cache when open |
| stale_cache_ttl | float | 300.0 | Max stale age to serve |
| timeout_ms | int | 5000 | Request timeout |

## See Also

- [API Reference](../reference/api.md) - DecisionCache configuration
- [Observability](observability.md) - Circuit breaker metrics

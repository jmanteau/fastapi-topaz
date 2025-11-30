# API Reference

Complete reference for all fastapi-topaz public exports.

---

## Configuration

### TopazConfig

::: fastapi_topaz.TopazConfig
    options:
      show_root_heading: false
      members:
        - check_decision
        - is_allowed
        - check_relation
        - check_relations
        - policy_path_for
        - create_client

---

### DecisionCache

::: fastapi_topaz.DecisionCache
    options:
      show_root_heading: false

---

## Authorization Dependencies

### require_policy_allowed

::: fastapi_topaz.require_policy_allowed
    options:
      show_root_heading: false

---

### require_policy_auto

::: fastapi_topaz.require_policy_auto
    options:
      show_root_heading: false

---

### require_rebac_allowed

::: fastapi_topaz.require_rebac_allowed
    options:
      show_root_heading: false

---

### get_authorized_resource

::: fastapi_topaz.get_authorized_resource
    options:
      show_root_heading: false

---

### filter_authorized_resources

::: fastapi_topaz.filter_authorized_resources
    options:
      show_root_heading: false

---

### require_rebac_hierarchy

::: fastapi_topaz.require_rebac_hierarchy
    options:
      show_root_heading: false

---

### HierarchyResult

::: fastapi_topaz.HierarchyResult
    options:
      show_root_heading: false
      members:
        - as_dict

---

## Middleware

### TopazMiddleware

::: fastapi_topaz.TopazMiddleware
    options:
      show_root_heading: false

---

### skip_middleware

::: fastapi_topaz.skip_middleware
    options:
      show_root_heading: false

---

### SkipMiddleware

::: fastapi_topaz.SkipMiddleware
    options:
      show_root_heading: false

---

## Circuit Breaker

### CircuitBreaker

::: fastapi_topaz.CircuitBreaker
    options:
      show_root_heading: false
      members:
        - state
        - status
        - should_allow_request
        - record_success
        - record_failure
        - get_fallback_decision
        - reset
        - is_failure_exception

---

### CircuitState

::: fastapi_topaz.CircuitState
    options:
      show_root_heading: false

---

### CircuitStatus

::: fastapi_topaz.CircuitStatus
    options:
      show_root_heading: false

---

## Connection Pool

### ConnectionPool

::: fastapi_topaz.ConnectionPool
    options:
      show_root_heading: false
      members:
        - configure
        - initialize
        - acquire
        - release
        - connection
        - status
        - close

---

### PoolStatus

::: fastapi_topaz.PoolStatus
    options:
      show_root_heading: false

---

## Audit Logging

### AuditLogger

::: fastapi_topaz.AuditLogger
    options:
      show_root_heading: false
      members:
        - log_decision
        - log_batch_check
        - log_unauthenticated_event

---

### AuditEvent

::: fastapi_topaz.AuditEvent
    options:
      show_root_heading: false
      members:
        - to_dict
        - to_json

---

## Observability

### PrometheusMetrics

::: fastapi_topaz.PrometheusMetrics
    options:
      show_root_heading: false
      members:
        - record_auth_request
        - record_cache_hit
        - record_cache_miss
        - record_latency
        - record_topaz_latency
        - record_error
        - set_circuit_state
        - record_circuit_transition
        - record_fallback
        - set_cache_size

---

### OTelTracing

::: fastapi_topaz.OTelTracing
    options:
      show_root_heading: false
      members:
        - start_auth_span
        - end_auth_span
        - start_cache_span
        - end_cache_span
        - start_topaz_span
        - end_topaz_span
        - record_error
        - get_current_trace_id

---

## Re-exported Types

These types are re-exported from `aserto.client` for convenience:

```python
from fastapi_topaz import (
    AuthorizerOptions,
    Identity,
    IdentityType,
    ResourceContext,
)
```

### AuthorizationError

::: fastapi_topaz.AuthorizationError
    options:
      show_root_heading: false

---

## Type Aliases

```python
from fastapi_topaz._defaults import (
    IdentityMapper,   # Callable[[], Identity]
    StringMapper,     # Callable[[], str]
    ObjectMapper,     # Callable[[], Obj]
    ResourceMapper,   # Callable[[], ResourceContext]
)
```

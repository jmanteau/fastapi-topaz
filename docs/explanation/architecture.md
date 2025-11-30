# Architecture and Design Decisions

This document explains the architectural decisions behind fastapi-topaz and how the components work together.

## System Overview

```mermaid
flowchart TB
    subgraph Client
        B[Browser/API Client]
    end

    subgraph FastAPI Application
        F[FastAPI Router]
        M[TopazMiddleware<br/><i>optional</i>]
        D[Dependencies<br/>require_policy_allowed<br/>require_rebac_allowed]
        H[Endpoint Handlers]
    end

    subgraph fastapi-topaz
        TC[TopazConfig]
        DC[DecisionCache]
        CB[CircuitBreaker]
        CP[ConnectionPool]
        AL[AuditLogger]
        OB[Observability<br/>Metrics + Tracing]
    end

    subgraph Topaz
        AU[Authorizer<br/>gRPC :8282]
        DS[Directory<br/>Relationships]
        PO[Policies<br/>Rego]
    end

    B --> F
    F --> M
    M --> D
    D --> H

    TC --> DC
    TC --> CB
    TC --> CP
    TC --> AL
    TC --> OB

    D --> TC
    M --> TC
    TC --> AU
    AU --> DS
    AU --> PO

    style TC fill:#6366f1,color:#fff
    style DC fill:#818cf8,color:#fff
    style CB fill:#818cf8,color:#fff
```

## Request Flow

### Policy Check Flow

When you use `require_policy_allowed()`, this is what happens:

```mermaid
sequenceDiagram
    participant C as Client
    participant F as FastAPI
    participant D as Dependency
    participant Cache as DecisionCache
    participant CB as CircuitBreaker
    participant T as Topaz

    C->>F: GET /documents
    F->>D: require_policy_allowed()

    D->>D: Extract identity

    D->>Cache: Check cache
    alt Cache hit
        Cache-->>D: cached=True/False
        D-->>F: allow/deny
    else Cache miss
        D->>CB: should_allow_request()
        alt Circuit open
            CB-->>D: use fallback
            D->>Cache: Get stale cache
            D-->>F: fallback decision
        else Circuit closed
            D->>T: decisions(policy_path)
            T-->>D: allowed=True/False
            D->>Cache: Store result
            D->>CB: record_success()
            D-->>F: allow/deny
        end
    end

    F-->>C: 200 OK / 403 Forbidden
```

### ReBAC Check Flow

When you use `require_rebac_allowed()`, the flow includes relationship checking:

```mermaid
sequenceDiagram
    participant C as Client
    participant F as FastAPI
    participant D as Dependency
    participant T as Topaz
    participant DS as Directory

    C->>F: PUT /documents/123
    F->>D: require_rebac_allowed("document", "can_write")

    D->>D: Extract identity (user_id)
    D->>D: Extract object_id from path (123)

    D->>D: Build resource_context
    Note right of D: object_type: document<br/>object_id: 123<br/>relation: can_write<br/>subject_type: user

    D->>T: decisions(myapp.check)
    T->>DS: check_relation(user:alice, can_write, document:123)
    DS-->>T: has_relation=True
    T-->>D: allowed=True

    D-->>F: allow
    F-->>C: 200 OK
```

### Circuit Breaker State Machine

The circuit breaker protects against Topaz failures:

```mermaid
stateDiagram-v2
    [*] --> Closed

    Closed --> Open: failure_threshold<br/>exceeded
    Open --> HalfOpen: recovery_timeout<br/>elapsed
    HalfOpen --> Closed: success_threshold<br/>met
    HalfOpen --> Open: test request<br/>failed

    note right of Closed
        Normal operation
        Requests go to Topaz
        Failures tracked
    end note

    note right of Open
        Topaz bypassed
        Fallback strategy used
        Timer running
    end note

    note right of HalfOpen
        Test request sent
        Success closes circuit
        Failure reopens
    end note
```

### Middleware vs Dependencies

fastapi-topaz offers two approaches to authorization:

```mermaid
flowchart TB
    subgraph "Middleware Approach"
        M1[Request] --> M2[TopazMiddleware]
        M2 --> M3{Authorized?}
        M3 -->|Yes| M4[Handler]
        M3 -->|No| M5[403 Response]
        M4 --> M6[Response]
    end

    subgraph "Dependency Approach"
        D1[Request] --> D2[Handler]
        D2 --> D3[require_*_allowed]
        D3 --> D4{Authorized?}
        D4 -->|Yes| D5[Continue]
        D4 -->|No| D6[HTTPException 403]
        D5 --> D7[Response]
    end
```

| Aspect | Middleware | Dependencies |
|--------|------------|--------------|
| Scope | Global (all routes) | Per-endpoint |
| Control | Less granular | Fine-grained |
| Testing | Harder to mock | Easy to override |
| Use case | Uniform policy | Mixed policies |

## Why Dependencies Over Decorators?

FastAPI's dependency injection is the native pattern:

```python
@router.put("/documents/{id}")
async def update_document(
    id: int,
    request: Request,
    _: None = Depends(require_rebac_allowed(config, "document", "can_write")),
):
    ...
```

Benefits:

| Benefit | Description |
|---------|-------------|
| Explicit | Authorization visible in function signature |
| Native | Uses FastAPI's standard pattern |
| Testable | Easy mock with `dependency_overrides` |
| Type-safe | Full IDE support |
| Simple | No signature magic needed |

## Policy Path Convention

fastapi-topaz uses a convention for policy paths:

```
{policy_root}.{METHOD}.{path.segments}
```

Examples:

| Route | Policy Path |
|-------|-------------|
| `GET /documents` | `myapp.GET.documents` |
| `POST /documents` | `myapp.POST.documents` |
| `GET /documents/123` | `myapp.GET.documents.__id` |
| `PUT /users/alice/settings` | `myapp.PUT.users.__id.settings` |

Path parameters are converted to `__paramname`.

## Caching Architecture

```mermaid
flowchart LR
    subgraph Cache Key
        U[identity_value]
        P[policy_path]
        D[decision]
        R[resource_context]
    end

    U --> H[SHA256 Hash]
    P --> H
    D --> H
    R --> H

    H --> K[Cache Key<br/>32 chars]

    subgraph DecisionCache
        K --> E[CacheEntry]
        E --> V[value: bool]
        E --> X[expires_at: float]
    end
```

Cache behavior:
- Caches decisions per `(user, policy_path, decision, resource_context)`
- Automatically expires entries after TTL
- Evicts oldest entries when `max_size` is reached
- Thread-safe with async lock

## Error Handling

All authorization failures result in `HTTPException(403)`:

```python
raise HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail=f"Access denied: {policy_path}",
)
```

To customize error handling, wrap the dependency:

```python
def custom_auth_check(config, policy_path):
    base_dep = require_policy_allowed(config, policy_path)

    async def wrapper(request: Request):
        try:
            await base_dep(request)
        except HTTPException:
            raise HTTPException(
                status_code=403,
                detail={"error": "unauthorized", "required_permission": policy_path}
            )

    return wrapper
```

## Performance Considerations

### Decision Caching

Enable optional TTL-based caching to avoid repeated authorization checks:

```python
cache = DecisionCache(ttl_seconds=60, max_size=1000)

config = TopazConfig(
    ...
    decision_cache=cache,
)
```

When to use:
- High-traffic endpoints with repeated checks
- Authorization decisions don't change frequently
- NOT for real-time permission changes

### Concurrent Bulk Authorization

`filter_authorized_resources()` uses `asyncio.gather()` for concurrent checks:

```python
config = TopazConfig(
    ...
    max_concurrent_checks=20,
)
```

Performance impact:
- 10 items with 50ms latency: ~50ms (concurrent) vs ~500ms (sequential)
- Semaphore prevents overwhelming the authorizer

### Connection Pooling

For high-throughput applications, use connection pooling:

```python
pool = ConnectionPool(min_connections=2, max_connections=10)

config = TopazConfig(
    ...
    connection_pool=pool,
)
```

Benefits:
- Reuses gRPC connections
- Reduces connection overhead
- Automatic health checking

## Comparison with Alternatives

| Feature | fastapi-topaz | casbin | fastapi-permissions |
|---------|---------------|--------|---------------------|
| Policy Engine | Topaz/OPA | Casbin | Custom |
| Policy Language | Rego | Model-based | Python |
| ReBAC Support | Yes | Limited | No |
| FastAPI Integration | Native | Adapter | Native |
| Distributed | Yes (edge) | No | No |
| Caching | Built-in | External | No |
| Circuit Breaker | Built-in | No | No |

## See Also

- [Authorization Models](authorization-models.md) - RBAC/ABAC/ReBAC concepts
- [API Reference](../reference/api.md) - Complete API documentation
- [Topaz Documentation](https://www.topaz.sh/docs)

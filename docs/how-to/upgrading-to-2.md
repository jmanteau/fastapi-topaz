# How to Upgrade from 1.x to 2.0

fastapi-topaz 2.0 removes the APIs deprecated in 1.2, and changes some behaviour you may rely on. Work through this page in order:

1. [Code that stops working](#code-that-stops-working). It fails at import or startup, so you find it quickly.
2. [Behaviour changes](#behaviour-changes). Nothing fails, but responses and decisions can differ.
3. [Tooling changes](#tooling-changes). These affect scripts and CI that use the CLI or the generated output.

If you run Python with `-W error::DeprecationWarning` on 1.2 and it passes, most of section 1 doesn't apply to you.

## Code that stops working

### `ConnectionPool` is removed

`ConnectionPool`, `PoolStatus` and `TopazConfig(connection_pool=...)` never had any effect. Every authorization check already shares one gRPC channel per `TopazConfig`. Delete the argument and the import:

```python
# 1.x
config = TopazConfig(..., connection_pool=ConnectionPool(max_connections=10))

# 2.0
config = TopazConfig(...)
```

### `TopazConfig.create_client()` is removed

Each call opened a channel you had to close, outside the cache and circuit breaker. Use the checking methods instead:

```python
# 1.x
client = config.create_client(request)
decisions = await client.decisions(policy_path="myapp.check", decisions=("allowed",), ...)

# 2.0
allowed = await config.is_allowed(request, "myapp.check", resource_context={...})
# or, for a relation
allowed = await config.check_relation(request, "document", doc_id, "can_share")
```

### `CircuitBreaker(timeout_ms=..., cache_priority=...)` are removed

Neither had any effect, and passing them now raises `TypeError`. If you set `timeout_ms` expecting a deadline, you were getting `check_timeout`'s 5-second default. Set the deadline where it takes effect:

```python
# 1.x
CircuitBreaker(timeout_ms=2000)

# 2.0
config = TopazConfig(..., check_timeout=2.0, circuit_breaker=CircuitBreaker())
```

### `AuthorizationError` and the `*Mapper` aliases are removed

Nothing raised `AuthorizationError`: denials are `HTTPException(403)`. An `except AuthorizationError:` block is dead code, so delete it. `IdentityMapper`, `StringMapper`, `ObjectMapper` and `ResourceMapper` were aliases for zero-argument callables; define your own `Callable` type if you used them.

### Custom cache backends need two keyword arguments

`CacheBackend.get()` and `.set()` are called with keyword-only `identity_type` and `policy_instance`. They must be part of your key: two identities of different types can share a value, and two configs can share one backend.

```python
class RedisCache:
    async def get(self, identity_value, policy_path, decision, resource_context,
                  *, identity_type="", policy_instance=""):
        ...

    async def set(self, identity_value, policy_path, decision, resource_context, value,
                  *, identity_type="", policy_instance=""):
        ...
```

The built-in `DecisionCache` is already updated. Either way, the key format changed, so the cache starts empty after the upgrade.

### Inputs that are now rejected at startup

These raised nothing in 1.x and silently misbehaved. They now raise `ValueError` when the config or dependency is created:

| Input | 1.x behaviour |
|-------|---------------|
| `require_rebac_hierarchy(config, [])` | Allowed every request |
| `require_rebac_allowed(..., object_id="")`, `get_authorized_resource(..., object_id="")`, an id source of `"static:"` | Checked an empty object ID |
| `TopazConfig(max_concurrent_checks=0)` | Deadlocked bulk checks |
| `DecisionCache(max_size=0)` | Grew without bound |
| Two `PrometheusMetrics` on one registry with the same prefix and different labels | Failed on every request |
| `TopazConfig(on_error=...)` or `TopazMiddleware(on_error=...)` with any value other than `"deny"`, `"unavailable"` (or `None` for the middleware) | Didn't exist |

## Behaviour changes

### Authorizer failures in dependencies follow `on_error`

When the Topaz call itself fails and the circuit breaker gives no fallback decision, 1.x dependencies let the exception escape as an unhandled 500. In 2.0 they answer like the middleware, per `TopazConfig(on_error=...)`:

- `"deny"` (default): 403 Forbidden.
- `"unavailable"`: 503 `{"detail": "Authorization service unavailable"}`, with `Retry-After` from the circuit breaker's `recovery_timeout`.

`TopazMiddleware(on_error=...)` now defaults to `None`, meaning "use the config"; an explicit value still overrides it. See [When the authorizer fails](middleware.md#when-the-authorizer-fails-on_error).

### Trusted resource context beats path parameters

The resource context sent to Topaz is merged as path parameters, then the dependency's static `resource_context`, then `resource_context_provider`. In 1.x path parameters came last, so a client could override a trusted value such as `tenant_id` through the URL. If a policy relied on a path parameter overriding provider data, rename one of the keys.

### `get_authorized_resource` authorizes before fetching

The fetcher now runs only after authorization succeeds. A denied request gets 403 whether or not the resource exists; in 1.x a missing resource returned 404 first, which revealed which IDs exist. Sync fetchers run in the threadpool, and async fetchers are awaited. That includes objects with an async `__call__`, and wrappers such as `lambda r: fetch(r)`.

### `require_policy_auto` on FastAPI 0.137+

On FastAPI 0.137 and later, 1.x built the policy path without the `include_router()` prefix: `myapp.POST` instead of `myapp.POST.api.folders`. 2.0 includes the prefix. If you wrote policies for the un-prefixed paths to work around this, rename them.

### Circuit breaker recovery

In the half-open state, only calls admitted as probes for the current recovery attempt decide whether the circuit closes or reopens. Slow calls admitted earlier no longer count. If you call the breaker directly, pass the ticket from the new `admit()` to `record_success()`, `record_failure()` and `release_probe()`. `should_allow_request()` and ticketless calls still work as before.

### Testing helpers

`install_mock` also replaces the config's `identity_provider`. Tests get `MockTopazConfig.identity_returns` as an `IDENTITY_TYPE_SUB` identity, or an unauthenticated identity for `None`. To test your own identity provider, call it directly.

## Tooling changes

| Tool | 2.0 behaviour | Action |
|------|---------------|--------|
| CLI | Exits with code 2 when the app or config can't be imported (was 1) | Update scripts that test for 1 |
| `generate-policies` / `generate_policies` | Keeps existing `.rego` files; pass `--overwrite` / `overwrite=True` to replace them. No skeletons for routes covered by a policy group or `default_policy` | Add `--overwrite` if you regenerate in place |
| Codegen, `policy-diff`, rights matrix | List the docs routes (`/docs`, `/openapi.json`, `/redoc`) and frontend routes and mounts, which the middleware authorizes | Add policies for them, or exclude them in the middleware |
| Same tools, plus `check` and `annotate_openapi` | Report routes the middleware skips (`@skip_middleware`, `SkipMiddleware`, `exclude_paths`, `exclude_methods`) as `skipped` | Update consumers that read `resolution_source` |
| `annotate_openapi` | `x-authz-policy` / `x-authz-source` are `{method: value}` maps when a route's methods resolve differently. Skipped operations get `x-authz-source: skipped` and no `x-authz-policy` | Accept both strings and maps |
| `policy-diff` | The first matching policy group decides, as in the middleware; a missing file for it reports the route missing | Add the missing group policy |

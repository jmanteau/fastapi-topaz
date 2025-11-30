# Troubleshooting Guide

Common issues and solutions when working with fastapi-topaz.

## Connection Issues

### "Connection refused" to Topaz

**Symptoms:**
```
ConnectionRefusedError: [Errno 111] Connection refused
```

**Solutions:**

1. **Check Topaz is running:**
   ```bash
   curl http://localhost:8383/api/v2/info
   # or for gRPC:
   grpcurl -plaintext localhost:8282 list
   ```

2. **Verify URL in config:**
   ```python
   # Correct:
   AuthorizerOptions(url="localhost:8282")

   # Wrong (don't include protocol):
   AuthorizerOptions(url="http://localhost:8282")
   ```

3. **Check network/firewall:**
   ```bash
   # If using Docker:
   docker-compose ps
   # Ensure containers are on same network
   ```

### "Deadline exceeded" / Timeout

**Symptoms:**
```
grpc._channel._InactiveRpcError: <_InactiveRpcError of RPC that terminated with:
    status = StatusCode.DEADLINE_EXCEEDED
```

**Solutions:**

1. **Increase timeout:**
   ```python
   AuthorizerOptions(url="localhost:8282", timeout=10)
   ```

2. **Enable circuit breaker:**
   ```python
   config = TopazConfig(
       ...
       circuit_breaker=CircuitBreaker(
           timeout_ms=5000,
           fallback="cache_then_deny",
       ),
   )
   ```

3. **Check Topaz health:**
   ```bash
   # Topaz may be overloaded or policy evaluation is slow
   docker logs topaz-container
   ```

---

## Authorization Issues

### Always Getting 403 Forbidden

**Symptoms:** Every request returns 403, even for admins.

**Debug steps:**

1. **Enable debug logging:**
   ```python
   import logging
   logging.getLogger("fastapi_topaz").setLevel(logging.DEBUG)
   ```

2. **Check identity extraction:**
   ```python
   def identity_provider(request: Request) -> Identity:
       user_id = request.headers.get("X-User-ID")
       print(f"DEBUG: Extracted user_id={user_id}")  # Add debug

       if not user_id:
           return Identity(type=IdentityType.IDENTITY_TYPE_NONE)

       return Identity(type=IdentityType.IDENTITY_TYPE_SUB, value=user_id)
   ```

3. **Verify policy path:**
   ```python
   # Print what policy path is being checked
   policy_path = config.policy_path_for("GET", "/documents/{id}")
   print(f"Policy path: {policy_path}")  # e.g., myapp.GET.documents.__id
   ```

4. **Test policy directly:**
   ```bash
   # Use topaz CLI to test
   topaz decision --decision allowed \
       --policy-path myapp.GET.documents \
       --identity-type sub \
       --identity alice
   ```

### Policy Not Found

**Symptoms:**
```
policy "myapp.GET.documents" not found
```

**Solutions:**

1. **Check policy_instance_name matches:**
   ```python
   config = TopazConfig(
       ...
       policy_instance_name="myapp",  # Must match Topaz config
   )
   ```

2. **Verify policy is loaded:**
   ```bash
   # List loaded policies
   topaz policy list
   ```

3. **Check Rego package name:**
   ```rego
   # policy.rego
   package myapp  # Must match policy_path_root

   GET.documents.allowed := true
   ```

### ReBAC Always Denied

**Symptoms:** ReBAC checks always return false, even for owners.

**Debug steps:**

1. **Check resource context:**
   ```python
   # Add logging to see what's being sent
   def resource_context_provider(request: Request) -> dict:
       ctx = {
           "owner_id": request.state.document.owner_id,
           "is_public": request.state.document.is_public,
       }
       print(f"DEBUG: resource_context={ctx}")
       return ctx
   ```

2. **Verify object_id resolution:**
   ```python
   # Explicit object_id
   require_rebac_allowed(config, "document", "can_read", object_id="123")

   # Or from path params (default)
   # Uses request.path_params["id"]
   ```

3. **Check directory relations:**
   ```bash
   # Query Topaz directory
   topaz directory get-relation \
       --subject-type user \
       --subject-id alice \
       --relation owner \
       --object-type document \
       --object-id 123
   ```

---

## Caching Issues

### Changes Not Taking Effect

**Symptoms:** Updated permissions in Topaz aren't reflected immediately.

**Solutions:**

1. **Clear cache:**
   ```python
   await config.decision_cache.clear()
   ```

2. **Reduce TTL for development:**
   ```python
   # Short TTL for development
   DecisionCache(ttl_seconds=5)

   # Longer TTL for production
   DecisionCache(ttl_seconds=60)
   ```

3. **Disable cache for specific checks:**
   ```python
   # Bypass cache by checking directly
   client = config.create_client(request)
   result = await client.decisions(...)
   ```

### Cache Not Working

**Symptoms:** Cache hit rate is 0%, every request hits Topaz.

**Debug steps:**

1. **Verify cache is configured:**
   ```python
   config = TopazConfig(
       ...
       decision_cache=DecisionCache(),  # Must be set!
   )
   ```

2. **Check cache keys are consistent:**
   ```python
   # Cache key includes resource_context
   # If context changes, cache won't hit
   def resource_context_provider(request: Request) -> dict:
       return {
           "id": request.path_params.get("id"),
           # Don't include timestamps or random values!
       }
   ```

3. **Enable metrics:**
   ```python
   config = TopazConfig(
       ...
       metrics=PrometheusMetrics(),
   )
   # Check topaz_cache_hits_total vs topaz_cache_misses_total
   ```

---

## Circuit Breaker Issues

### Circuit Opens Too Quickly

**Symptoms:** Circuit breaker opens after minor network blips.

**Solutions:**

```python
circuit_breaker=CircuitBreaker(
    failure_threshold=10,     # Increase from default 5
    recovery_timeout=60,      # Longer recovery time
    success_threshold=3,      # More successes needed to close
)
```

### Fallback Not Working

**Symptoms:** When circuit is open, requests fail instead of using fallback.

**Debug steps:**

1. **Check fallback strategy:**
   ```python
   circuit_breaker=CircuitBreaker(
       fallback="cache_then_deny",  # Uses stale cache first
   )
   ```

2. **Verify stale cache is enabled:**
   ```python
   circuit_breaker=CircuitBreaker(
       serve_stale_cache=True,
       stale_cache_ttl=300,  # 5 minutes
   )
   ```

3. **Check circuit status:**
   ```python
   @app.get("/health")
   async def health():
       if config.circuit_breaker:
           status = config.circuit_breaker.status()
           return {
               "circuit_state": status.state,
               "failure_count": status.failure_count,
           }
   ```

---

## Middleware Issues

### Middleware Not Applied

**Symptoms:** Routes aren't being protected by TopazMiddleware.

**Solutions:**

1. **Check middleware order:**
   ```python
   # Middleware is added in reverse order
   # TopazMiddleware should be added LAST
   app.add_middleware(CORSMiddleware, ...)
   app.add_middleware(TopazMiddleware, config=config)  # Added last, runs first
   ```

2. **Check exclusion patterns:**
   ```python
   TopazMiddleware(
       app,
       config=config,
       exclude_paths=[r"^/health$", r"^/docs.*"],  # Regex patterns
   )
   ```

3. **Check route is matched:**
   ```python
   # Middleware only protects routes that exist
   # 404s pass through without authorization
   ```

### Routes Excluded Unexpectedly

**Symptoms:** Some routes aren't being protected.

**Debug steps:**

1. **Check @skip_middleware decorator:**
   ```python
   # This route is excluded:
   @app.get("/special")
   @skip_middleware
   async def special():
       ...
   ```

2. **Check router dependencies:**
   ```python
   # This entire router is excluded:
   router = APIRouter(dependencies=[Depends(SkipMiddleware)])
   ```

---

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `Identity has no value` | identity_provider returned None/empty | Check header extraction, authentication |
| `policy_path must not be empty` | Empty policy path | Check policy_path_root configuration |
| `ConnectionPool is closed` | Pool used after shutdown | Don't reuse config after app shutdown |
| `Semaphore released too many times` | Bug in custom code | Check async context managers |

---

## Getting Help

If you're still stuck:

1. **Enable full debug logging:**
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

2. **Check Topaz logs:**
   ```bash
   docker logs topaz-container -f
   ```

3. **Simplify to minimal example:**
   ```python
   # Create minimal reproduction case
   from fastapi import FastAPI, Depends
   from fastapi_topaz import TopazConfig, require_policy_allowed
   # ... minimal config ...
   ```

4. **Report issues:** [GitHub Issues](https://github.com/opcr-io/topaz/issues)

## See Also

- [Testing](testing.md) - Mock authorization in tests
- [Circuit Breaker](circuit-breaker.md) - Resilience configuration
- [Observability](observability.md) - Monitoring and debugging

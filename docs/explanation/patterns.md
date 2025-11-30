# Patterns and Anti-Patterns

Common patterns for effective authorization with fastapi-topaz, and anti-patterns to avoid.

---

## Patterns

### Pattern: Conditional UI Elements

Check permissions without blocking to show/hide UI elements.

```python
@app.get("/documents/{id}")
async def get_document(
    id: int,
    request: Request,
    # Main authorization - blocks if denied
    _: None = Depends(require_rebac_allowed(config, "document", "can_read")),
):
    doc = await fetch_document(id)

    # Additional permission checks for UI hints (non-blocking)
    permissions = await config.check_relations(
        request,
        object_type="document",
        object_id=str(id),
        relations=["can_write", "can_delete", "can_share"],
    )

    return {
        "document": doc,
        "permissions": permissions,
        # Frontend can use this to show/hide edit, delete, share buttons
    }
```

**Why this works:**
- Main check uses `Depends()` to block unauthorized access
- Permission hints use `check_relations()` which never raises
- Single API call returns everything frontend needs

---

### Pattern: Multi-Tenant Authorization

Scope all authorization to the current tenant.

```python
def resource_context_provider(request: Request) -> dict:
    """Include tenant_id in all authorization checks."""
    return {
        "tenant_id": request.headers.get("X-Tenant-ID"),
        **request.path_params,
    }

config = TopazConfig(
    ...
    resource_context_provider=resource_context_provider,
)
```

```rego
# Rego policy
package myapp

import rego.v1

# Tenant isolation - always check tenant_id matches
tenant_match if {
    input.resource.tenant_id == input.user.tenant_id
}

GET.documents.allowed if {
    tenant_match
    # ... other checks
}
```

**Why this works:**
- Tenant context is automatically included in every check
- Rego policies enforce tenant isolation
- Impossible to accidentally skip tenant check

---

### Pattern: Hierarchical Resources

Model org → team → project → document hierarchies.

```python
@app.get("/projects/{project_id}/documents/{doc_id}")
async def get_document(
    project_id: int,
    doc_id: int,
    request: Request,
    # Check project access (implies document access)
    _: None = Depends(require_rebac_allowed(config, "project", "can_read")),
):
    ...
```

```rego
# Rego policy - inherit permissions from parent
package myapp

import rego.v1

# User can read document if they can read the parent project
check.allowed if {
    input.resource.relation == "can_read"
    input.resource.object_type == "document"
    project_id := data.documents[input.resource.object_id].project_id
    ds.check({
        "object_type": "project",
        "object_id": project_id,
        "relation": "can_read",
        "subject_type": "user",
        "subject_id": input.identity.value,
    })
}
```

**Why this works:**
- Checks at the container level (project) inherit down
- Reduces number of explicit relations needed
- Matches real-world permission models

---

### Pattern: Rate-Limited Sensitive Operations

Combine authorization with rate limiting for sensitive actions.

```python
from slowapi import Limiter

limiter = Limiter(key_func=lambda r: r.state.user_id)

@app.delete("/documents/{id}")
@limiter.limit("5/hour")
async def delete_document(
    id: int,
    _: None = Depends(require_rebac_allowed(config, "document", "can_delete")),
):
    # Even authorized users can only delete 5 docs/hour
    ...
```

**Why this works:**
- Authorization checks "can they do this?"
- Rate limiting checks "should they do this now?"
- Defense in depth against compromised accounts

---

### Pattern: Audit Trail Integration

Log authorization decisions for compliance.

```python
from fastapi_topaz import AuditLogger

audit = AuditLogger(
    log_allowed=True,
    log_denied=True,
    include_resource_context=True,
)

config = TopazConfig(
    ...
    audit_logger=audit,
)
```

Output:
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "event": "authorization.dependency.denied",
  "identity": {"type": "sub", "value": "alice"},
  "authorization": {
    "policy_path": "myapp.DELETE.documents.__id",
    "decision": "denied",
    "latency_ms": 12.5
  },
  "request": {"method": "DELETE", "path": "/documents/123"}
}
```

**Why this works:**
- Every decision is logged with context
- Easy to answer "who tried to access what and when?"
- Compliance-ready structured logs

---

## Anti-Patterns

### Anti-Pattern: Over-Caching

**Problem:** Caching authorization decisions for too long.

```python
# BAD: 24 hour cache TTL
cache = DecisionCache(ttl_seconds=86400)
```

**Why it's bad:**
- Permission changes take 24 hours to propagate
- Revoked access remains effective for hours
- Security incident response is delayed

**Better:**

```python
# GOOD: Short TTL with circuit breaker
cache = DecisionCache(ttl_seconds=60, max_size=10000)

config = TopazConfig(
    decision_cache=cache,
    circuit_breaker=CircuitBreaker(
        serve_stale_cache=True,
        stale_cache_ttl=300,  # Only use stale cache when Topaz is down
    ),
)
```

---

### Anti-Pattern: Authorization in Business Logic

**Problem:** Mixing authorization checks with business logic.

```python
# BAD: Authorization mixed with business logic
@app.put("/documents/{id}")
async def update_document(id: int, request: Request, body: DocumentUpdate):
    doc = await fetch_document(id)

    # Authorization buried in handler
    if doc.owner_id != request.state.user_id:
        if not request.state.user.is_admin:
            raise HTTPException(403)

    # Business logic
    doc.title = body.title
    await save_document(doc)
```

**Why it's bad:**
- Authorization logic scattered across handlers
- Easy to forget checks in new endpoints
- Hard to audit what permissions are required

**Better:**

```python
# GOOD: Authorization via dependencies
@app.put("/documents/{id}")
async def update_document(
    id: int,
    body: DocumentUpdate,
    _: None = Depends(require_rebac_allowed(config, "document", "can_write")),
):
    # Handler only contains business logic
    doc = await fetch_document(id)
    doc.title = body.title
    await save_document(doc)
```

---

### Anti-Pattern: Too Many Dependencies Per Route

**Problem:** Multiple authorization dependencies on one route.

```python
# BAD: Multiple overlapping checks
@app.put("/documents/{id}")
async def update_document(
    id: int,
    _policy: None = Depends(require_policy_allowed(config, "myapp.PUT.documents")),
    _rebac_write: None = Depends(require_rebac_allowed(config, "document", "can_write")),
    _rebac_read: None = Depends(require_rebac_allowed(config, "document", "can_read")),
    _tenant: None = Depends(require_tenant_access(config)),
):
    ...
```

**Why it's bad:**
- Multiple round-trips to Topaz
- Redundant checks (can_write implies can_read)
- Hard to understand what's actually checked

**Better:**

```python
# GOOD: Single check with Rego handling complexity
@app.put("/documents/{id}")
async def update_document(
    id: int,
    _: None = Depends(require_rebac_allowed(config, "document", "can_write")),
):
    ...
```

```rego
# Let Rego handle the logic
check.allowed if {
    input.resource.relation == "can_write"
    # Rego can check tenant, role, and relationship in one evaluation
    tenant_match
    has_write_permission
}
```

---

### Anti-Pattern: Ignoring Authorization Errors

**Problem:** Catching and ignoring authorization failures.

```python
# BAD: Swallowing authorization errors
@app.get("/documents/{id}")
async def get_document(id: int, request: Request):
    try:
        await require_rebac_allowed(config, "document", "can_read")(request)
    except HTTPException:
        pass  # Ignore and continue anyway!

    doc = await fetch_document(id)
    return doc
```

**Why it's bad:**
- Defeats the purpose of authorization
- Security vulnerability
- Audit logs will show "allowed" when it wasn't

**Better:**

```python
# GOOD: Let failures propagate or handle intentionally
@app.get("/documents/{id}")
async def get_document(
    id: int,
    _: None = Depends(require_rebac_allowed(config, "document", "can_read")),
):
    # Only reaches here if authorized
    doc = await fetch_document(id)
    return doc
```

---

### Anti-Pattern: Dynamic Policy Paths from User Input

**Problem:** Using user input to construct policy paths.

```python
# BAD: User controls policy path
@app.get("/resource/{resource_type}/{id}")
async def get_resource(resource_type: str, id: int, request: Request):
    # Attacker can request: /resource/admin.settings/1
    policy_path = f"myapp.GET.{resource_type}"
    await require_policy_allowed(config, policy_path)(request)
```

**Why it's bad:**
- User can access policies they shouldn't
- Policy path injection
- Bypasses intended authorization model

**Better:**

```python
# GOOD: Allowlist resource types
ALLOWED_TYPES = {"document", "folder", "comment"}

@app.get("/resource/{resource_type}/{id}")
async def get_resource(resource_type: str, id: int, request: Request):
    if resource_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Invalid resource type")

    # Or use require_policy_auto which derives from route
    await require_policy_auto(config)(request)
```

---

## Summary

| Do | Don't |
|----|-------|
| Use dependencies for authorization | Mix auth in business logic |
| Keep cache TTL short (60s) | Cache for hours/days |
| Let Rego handle complex logic | Add many Python dependencies |
| Log all decisions | Silently swallow errors |
| Validate user input | Build policy paths from input |

## See Also

- [Choosing Authorization Approach](../how-to/choosing-authorization-approach.md) - Pick the right pattern
- [Architecture](architecture.md) - Design decisions
- [Testing](../how-to/testing.md) - Test patterns

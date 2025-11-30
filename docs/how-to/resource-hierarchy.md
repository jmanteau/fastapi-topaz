# How to Authorize Hierarchical Resources

Authorize access to nested resources like `/orgs/{org}/projects/{proj}/docs/{doc}` with a single dependency.

## Basic Usage

```python
from fastapi import Depends, FastAPI
from fastapi_topaz import TopazConfig, require_rebac_hierarchy

app = FastAPI()

@app.get("/orgs/{org_id}/projects/{proj_id}/docs/{doc_id}")
async def get_doc(
    _=Depends(require_rebac_hierarchy(config, [
        ("organization", "org_id", "member"),
        ("project", "proj_id", "viewer"),
        ("document", "doc_id", "can_read"),
    ])),
):
    ...
```

This replaces three separate `require_rebac_allowed` dependencies with one.

## Check Modes

### Mode "all" (default)

All checks must pass. Fails fast on first denial:

```python
require_rebac_hierarchy(config, checks, mode="all")
# org.member AND project.viewer AND document.can_read
```

### Mode "any"

At least one check must pass:

```python
require_rebac_hierarchy(config, [
    ("document", "doc_id", "owner"),
    ("document", "doc_id", "editor"),
    ("document", "doc_id", "viewer"),
], mode="any")
# owner OR editor OR viewer
```

### Mode "first_match"

Returns on first success (for permission escalation):

```python
require_rebac_hierarchy(config, [
    ("document", "doc_id", "owner"),
    ("document", "doc_id", "editor"),
    ("document", "doc_id", "viewer"),
], mode="first_match")
# Returns first matching relation
```

## ID Source Options

Each check tuple is `(object_type, id_source, relation)`. ID sources:

| Format | Description | Example |
|--------|-------------|---------|
| `"param_name"` | Path parameter | `"org_id"` |
| `"header:X-Name"` | Request header | `"header:X-Tenant-ID"` |
| `"query:name"` | Query parameter | `"query:account_id"` |
| `"static:value"` | Static value | `"static:global"` |
| `callable` | Function | `lambda r: r.state.tenant_id` |

## Non-Raising Check

Use `check_hierarchy()` when you need the result without raising:

```python
@app.get("/orgs/{org_id}/projects/{proj_id}")
async def get_project(request: Request, org_id: str, proj_id: str):
    result = await config.check_hierarchy(
        request,
        checks=[
            ("organization", "org_id", "member"),
            ("project", "proj_id", "viewer"),
        ],
    )
    return {
        "allowed": result.allowed,
        "denied_at": result.denied_at,
        "access_chain": result.as_dict(),
    }
```

## Performance

With `optimize=True` (default), checks for modes "all" and "any" run concurrently, reducing latency from `N * latency` to `~latency`.

## See Also

- [API Reference](../reference/api.md#require_rebac_hierarchy)
- [Authorization Models](../explanation/authorization-models.md)

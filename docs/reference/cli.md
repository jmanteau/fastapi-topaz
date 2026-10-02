# CLI Reference

Command-line tools for policy generation and validation.

## Installation

```bash
pip install fastapi-topaz
```

Commands import the app and config with `module:attribute` paths. The current working directory is added to `sys.path`, so `--app myapp:app` finds `./myapp.py` when run from the project root. If the app or config cannot be imported, the command exits with code 2.

## Commands

### generate-policies

Generate Rego policy skeletons from FastAPI routes.

```bash
fastapi-topaz generate-policies --app myapp.main:app --output policies/
```

Options:

| Option | Required | Description |
|--------|----------|-------------|
| `--app` | Yes | FastAPI app import path (module:variable) |
| `--output` | Yes | Output directory for generated policies |
| `--config` | No | TopazConfig import path |
| `--overwrite` | No | Overwrite existing policy files |
| `--dry-run` | No | Print policies without writing files |
| `--format` | No | Output format: `nested` (default) or `flat` |

Existing policy files are kept by default and reported as `SKIP`; pass `--overwrite` to replace them.

Example:

```bash
fastapi-topaz generate-policies \
  --app myapp.main:app \
  --output policies/ \
  --config myapp.config:topaz_config \
  --format flat \
  --overwrite
```

Output:
```
Scanning routes...
Generated policies/myapp.GET.documents.rego
Generated policies/myapp.POST.documents.rego
Generated policies/myapp.DELETE.documents.__id.rego
Generated 3 policies from 3 routes
```

### policy-diff

Compare routes against existing policies. Returns exit code 1 if mismatches found.

```bash
fastapi-topaz policy-diff --app myapp.main:app --policies policies/
```

Options:

| Option | Required | Description |
|--------|----------|-------------|
| `--app` | Yes | FastAPI app import path |
| `--policies` | Yes | Directory containing policy files |
| `--config` | No | TopazConfig import path |
| `--strict` | No | Fail on orphaned policies (no matching route) |
| `--format` | No | Output format: `text` (default), `json`, `markdown` |

Example:

```bash
fastapi-topaz policy-diff --app myapp.main:app --policies policies/ --strict
```

Output:
```
Scanning routes... 12 routes found
Scanning policies... 10 policies found

Missing policies (routes without policies):
  - myapp.DELETE.documents.__id
    Route: DELETE /documents/{id}

Orphaned policies (no matching route):
  - myapp.GET.old_endpoint

Summary: 1 missing, 1 orphaned
Exit code: 1
```

### policy-map

Display route-to-policy mapping.

```bash
fastapi-topaz policy-map --app myapp.main:app
```

Options:

| Option | Required | Description |
|--------|----------|-------------|
| `--app` | Yes | FastAPI app import path |
| `--config` | No | TopazConfig import path; its `policy_path_root` and `policy_path_normalizer` are used for the policy paths |
| `--root` | No | Policy path root when `--config` is not given (default: app) |
| `--format` | No | Output format: `text`, `json`, `markdown` |
| `--policies` | No | Check against existing policies |

Example (Markdown):

```bash
fastapi-topaz policy-map --app myapp.main:app --format markdown
```

Output:
```markdown
| Route | Method | Policy Path |
|-------|--------|-------------|
| /documents | GET | myapp.GET.documents |
| /documents | POST | myapp.POST.documents |
| /documents/{id} | GET | myapp.GET.documents.__id |
| /documents/{id} | DELETE | myapp.DELETE.documents.__id |
```

### check

Resolve which policy guards a concrete request URL, and optionally evaluate the decision against a live authorizer. Useful for debugging why a request hits an unexpected policy.

```bash
fastapi-topaz check --app myapp.main:app --method GET --path /documents/1
```

Options:

| Option | Required | Description |
|--------|----------|-------------|
| `--app` | Yes | FastAPI app import path (module:variable) |
| `--method` | Yes | HTTP method (e.g. GET) |
| `--path` | Yes | Concrete URL path (e.g. /documents/1, not the route template) |
| `--config` | No | TopazConfig import path |
| `--root` | No | Policy path root (default: app) |
| `--policies` | No | Policies directory (enables the explicit resolution tier) |
| `--live` | No | Also evaluate the `allowed` decision against the authorizer |
| `--identity` | No | Identity value for `--live` (sent as IDENTITY_TYPE_SUB) |

Output:
```
Route:    GET /documents/{id}
Policy:   myapp.GET.documents.__id
Source:   generated
Params:   {'id': '1'}
```

With `--live`, a `Decision: allowed` or `Decision: denied` line is appended. Exit codes: 0 allowed (or offline resolution succeeded), 1 denied, 2 error (no matching route or authorizer failure).

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Policy mismatch found (missing or orphaned) |
| 2 | Invalid arguments or configuration, including an app or config that cannot be imported |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TOPAZ_URL` | Default Topaz authorizer URL |
| `TOPAZ_POLICY_ROOT` | Default policy path root |

## See Also

- [Policy Generation How-to](../how-to/policy-generation.md) - Usage examples
- [API Reference](api.md) - Python API

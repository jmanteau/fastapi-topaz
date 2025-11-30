# CLI Reference

Command-line tools for policy generation and validation.

## Installation

```bash
pip install fastapi-topaz
```

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
| `--config` | No | TopazConfig import path |
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

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Policy mismatch found (missing or orphaned) |
| 2 | Invalid arguments or configuration |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TOPAZ_URL` | Default Topaz authorizer URL |
| `TOPAZ_POLICY_ROOT` | Default policy path root |

## See Also

- [Policy Generation How-to](../how-to/policy-generation.md) - Usage examples
- [API Reference](api.md) - Python API

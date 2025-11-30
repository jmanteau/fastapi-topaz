# FastAPI-Topaz

FastAPI middleware for [Topaz](https://www.topaz.sh/) authorization.

[![PyPI](https://img.shields.io/pypi/v/fastapi-topaz)](https://pypi.org/project/fastapi-topaz/) [![Python Version](https://img.shields.io/pypi/pyversions/fastapi-topaz)](https://pypi.org/project/fastapi-topaz/) [![License](https://img.shields.io/pypi/l/fastapi-topaz)](https://github.com/jmanteau/fastapi-topaz/blob/main/LICENSE) [![Downloads](https://img.shields.io/pypi/dm/fastapi-topaz)](https://pypi.org/project/fastapi-topaz/)

Full documentation following the [Diataxis](https://diataxis.fr/) framework available at **[jmanteau.github.io/fastapi-topaz](https://jmanteau.github.io/fastapi-topaz)**.

## Installation

```bash
pip install fastapi-topaz
```

## Quick Start

```python
from fastapi import Depends, FastAPI, Request
from fastapi_topaz import (
    AuthorizerOptions,
    Identity,
    IdentityType,
    TopazConfig,
    require_policy_allowed,
)

config = TopazConfig(
    authorizer_options=AuthorizerOptions(url="localhost:8282"),
    policy_path_root="myapp",
    identity_provider=lambda req: Identity(
        type=IdentityType.IDENTITY_TYPE_SUB,
        value=req.state.user_id,
    ),
    policy_instance_name="myapp",
)

app = FastAPI()

@app.get("/documents")
async def list_documents(
    request: Request,
    _: None = Depends(require_policy_allowed(config, "myapp.GET.documents")),
):
    return {"documents": [...]}
```
## Features

| Feature                    | Description                               |
| -------------------------- | ----------------------------------------- |
| Policy-based authorization | `require_policy_allowed()`                |
| ReBAC (relationship-based) | `require_rebac_allowed()`                 |
| Fetch + authorize          | `get_authorized_resource()`               |
| Bulk filtering             | `filter_authorized_resources()`           |
| Decision caching           | Configurable TTL cache                    |
| Circuit breaker            | Graceful degradation                      |
| Audit logging              | Structured JSON logging                   |
| Observability              | Prometheus metrics, OpenTelemetry tracing |


## Documentation

| Section                                                                                           | Focus                  | Description                        |
| ------------------------------------------------------------------------------------------------- | ---------------------- | ---------------------------------- |
| [Tutorials](https://jmanteau.github.io/fastapi-topaz/tutorials/getting-started/)                  | Learning-Oriented      | Step-by-step guides to get started |
| [How-To Guides](https://jmanteau.github.io/fastapi-topaz/how-to/choosing-authorization-approach/) | Task-Oriented          | Solve specific problems            |
| [Reference](https://jmanteau.github.io/fastapi-topaz/reference/api/)                              | Information-Oriented   | API and CLI specifications         |
| [Explanation](https://jmanteau.github.io/fastapi-topaz/explanation/architecture/)                 | Understanding-Oriented | Architecture and concepts          |

## Requirements

- Python 3.9+
- FastAPI 0.100+
- Running Topaz instance

## Links

- [Topaz Documentation](https://www.topaz.sh/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

## License

Apache 2.0

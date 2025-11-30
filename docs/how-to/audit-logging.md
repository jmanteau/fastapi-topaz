# How to Configure Audit Logging

Structured JSON logging for all authorization decisions. Designed for compliance (SOC2, HIPAA, GDPR).

## Basic Configuration

```python
from fastapi_topaz import TopazConfig, AuditLogger

config = TopazConfig(
    authorizer_options=AuthorizerOptions(url="localhost:8282"),
    policy_path_root="myapp",
    identity_provider=get_identity,
    policy_instance_name="myapp",

    audit_logger=AuditLogger(
        log_allowed=True,
        log_denied=True,
        log_skipped=False,
        log_unauthenticated=True,
        log_manual_checks=False,
        include_resource_context=True,
    ),
)
```

## Event Types

```
authorization.middleware.allowed      # Policy check passed
authorization.middleware.denied       # Policy check failed (403)
authorization.middleware.skipped      # Route excluded
authorization.middleware.unauthenticated  # No identity (401)
authorization.dependency.allowed      # Dependency check passed
authorization.dependency.denied       # Dependency check failed
authorization.check.allowed           # is_allowed() returned True
authorization.check.denied            # is_allowed() returned False
```

## Log Schema

### Allowed Access

```json
{
  "timestamp": "2024-01-15T10:30:00.123Z",
  "level": "INFO",
  "event": "authorization.middleware.allowed",
  "request_id": "req-789",
  "identity": {
    "type": "sub",
    "value": "user-123"
  },
  "authorization": {
    "policy_path": "myapp.GET.documents.__id",
    "decision": "allowed",
    "cached": false,
    "latency_ms": 2.3
  },
  "request": {
    "method": "GET",
    "path": "/documents/456",
    "ip": "192.168.1.100"
  }
}
```

### Denied Access

```json
{
  "timestamp": "2024-01-15T10:31:00.456Z",
  "level": "WARN",
  "event": "authorization.denied",
  "identity": {"type": "sub", "value": "user-456"},
  "authorization": {"policy_path": "myapp.DELETE.documents", "decision": "denied"},
  "request": {"method": "DELETE", "path": "/documents/789"}
}
```

## Custom Handler

Send to SIEM (Splunk, Datadog):

```python
async def send_to_splunk(event: AuditEvent) -> None:
    await splunk_client.send(event.to_dict())

config = TopazConfig(
    ...
    audit_logger=AuditLogger(handler=send_to_splunk),
)
```

Multiple outputs:

```python
async def multi_handler(event: AuditEvent) -> None:
    logger.info(event.to_json())
    await splunk_client.send(event.to_dict())
    metrics.increment("auth_decisions", tags={"decision": event.decision})

config = TopazConfig(
    audit_logger=AuditLogger(handler=multi_handler),
)
```

## Query Examples

```sql
-- Who accessed document-123 in the last 24 hours?
SELECT identity.value, timestamp, authorization.decision
FROM auth_logs
WHERE resource.object_id = 'document-123'
  AND timestamp > NOW() - INTERVAL '24 hours'

-- Denied requests by user
SELECT identity.value, COUNT(*) as denied_count
FROM auth_logs
WHERE authorization.decision = 'denied'
GROUP BY identity.value
ORDER BY denied_count DESC
```

## Configuration Reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| log_allowed | bool | True | Log successful authorizations |
| log_denied | bool | True | Log denied authorizations |
| log_skipped | bool | False | Log excluded routes |
| log_unauthenticated | bool | True | Log 401 events |
| log_manual_checks | bool | False | Log is_allowed() calls |
| include_resource_context | bool | True | Include resource details |
| handler | Callable | None | Custom async handler |

## See Also

- [Middleware](middleware.md) - Middleware integration
- [Observability](observability.md) - Metrics and tracing

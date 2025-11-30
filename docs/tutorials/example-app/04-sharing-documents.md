# Sharing Documents Tutorial

Implement document sharing with read/write permissions using ReBAC.

**Time:** 20 minutes

## What You Will Learn

- Share documents with specific permissions
- Implement read vs write access
- Test permission-based access

## Prerequisites

- Services running (`make up`)
- Completed authorization tutorial
- Test cookies available (`make cookies`)

## Part 1: Sharing Logic

### Step 1: Understanding the Policy

File: `policies/common.rego`

```rego
has_share_permission(permission) if {
    user_sub
    some share in input.resource.shares
    share.user_id == user_sub
    share.permission == permission
}

can_read_document if {
    has_share_permission("read")
}

can_write_document if {
    has_share_permission("write")
}
```

The policy checks if the user has a share entry with the required permission.

### Step 2: Share a Document

Create document as Alice:
```bash
DOC_ID=$(curl -X POST -H "Cookie: session=$ALICE_SESSION_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"name": "Shared Doc", "content": "content"}' \
  http://localhost:8000/api/documents | jq -r '.id')
```

Bob cannot access:
```bash
curl -H "Cookie: session=$BOB_SESSION_COOKIE" \
  http://localhost:8000/api/documents/$DOC_ID
# Response: 403 Forbidden
```

Alice shares with Bob (read permission):
```bash
curl -X POST -H "Cookie: session=$ALICE_SESSION_COOKIE" \
  -H "Content-Type: application/json" \
  -d "{\"document_id\": $DOC_ID, \"user_email\": \"bob@example.com\", \"permission\": \"read\"}" \
  http://localhost:8000/api/shares
```

Bob can now read:
```bash
curl -H "Cookie: session=$BOB_SESSION_COOKIE" \
  http://localhost:8000/api/documents/$DOC_ID
# Response: 200 OK
```

Bob cannot write:
```bash
curl -X PUT -H "Cookie: session=$BOB_SESSION_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"name": "Modified", "content": "new content"}' \
  http://localhost:8000/api/documents/$DOC_ID
# Response: 403 Forbidden
```

## Part 2: Permission Levels

### Step 3: Understanding Permission Hierarchy

| Permission | Can Read | Can Write | Can Delete | Can Share |
|------------|----------|-----------|------------|-----------|
| Owner | Yes | Yes | Yes | Yes |
| Write | Yes | Yes | No | No |
| Read | Yes | No | No | No |
| None | No | No | No | No |

### Step 4: Upgrade Permission

Alice upgrades Bob to write:
```bash
curl -X PUT -H "Cookie: session=$ALICE_SESSION_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"permission": "write"}' \
  http://localhost:8000/api/shares/$DOC_ID/bob@example.com
```

Bob can now write:
```bash
curl -X PUT -H "Cookie: session=$BOB_SESSION_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"name": "Modified by Bob", "content": "new content"}' \
  http://localhost:8000/api/documents/$DOC_ID
# Response: 200 OK
```

### Step 5: Revoke Access

Alice revokes Bob's access:
```bash
curl -X DELETE -H "Cookie: session=$ALICE_SESSION_COOKIE" \
  http://localhost:8000/api/shares/$DOC_ID/bob@example.com
```

Bob cannot access:
```bash
curl -H "Cookie: session=$BOB_SESSION_COOKIE" \
  http://localhost:8000/api/documents/$DOC_ID
# Response: 403 Forbidden
```

## Part 3: Public Documents

### Step 6: Make Document Public

```bash
curl -X PUT -H "Cookie: session=$ALICE_SESSION_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"is_public": true}' \
  http://localhost:8000/api/documents/$DOC_ID
```

Any authenticated user can read:
```bash
curl -H "Cookie: session=$CHARLIE_SESSION_COOKIE" \
  http://localhost:8000/api/documents/$DOC_ID
# Response: 200 OK
```

Only owner can write:
```bash
curl -X PUT -H "Cookie: session=$CHARLIE_SESSION_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"content": "hacked"}' \
  http://localhost:8000/api/documents/$DOC_ID
# Response: 403 Forbidden
```

### Step 7: Policy for Public Documents

File: `policies/common.rego`

```rego
can_read_document if {
    input.resource.is_public == true
}
```

Public documents are readable by all authenticated users but only writable by owners.

## Part 4: Testing Sharing

### Step 8: Write Integration Tests

File: `integration-tests/tests/test_sharing.py`

```python
def test_sharing_permissions(alice_client, bob_client):
    # Alice creates document
    doc = alice_client.post("/api/documents", json={
        "name": "Shared Doc",
        "content": "content"
    }).json()

    # Bob cannot access initially
    response = bob_client.get(f"/api/documents/{doc['id']}")
    assert response.status_code == 403

    # Alice shares with Bob
    alice_client.post("/api/shares", json={
        "document_id": doc["id"],
        "user_email": "bob@example.com",
        "permission": "read"
    })

    # Bob can now read
    response = bob_client.get(f"/api/documents/{doc['id']}")
    assert response.status_code == 200

    # Bob cannot write
    response = bob_client.put(
        f"/api/documents/{doc['id']}",
        json={"content": "modified"}
    )
    assert response.status_code == 403
```

Run tests:
```bash
cd integration-tests
uv run pytest tests/test_sharing.py -v
```

## Summary

| Action | API Endpoint | Method |
|--------|--------------|--------|
| Share document | `/api/shares` | POST |
| Update permission | `/api/shares/{doc_id}/{email}` | PUT |
| Revoke access | `/api/shares/{doc_id}/{email}` | DELETE |
| Make public | `/api/documents/{id}` | PUT (is_public=true) |

## Next Steps

- [Authorization Models](../../explanation/authorization-models.md) - RBAC/ABAC/ReBAC concepts
- [Testing](../../how-to/testing.md) - Testing authorization in detail
- [API Reference](../../reference/api.md) - Complete API documentation

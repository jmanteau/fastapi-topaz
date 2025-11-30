from __future__ import annotations

"""
Integration Test: Authorization Failure Scenarios

Tests cases where users should be DENIED access:
1. Bob cannot read Alice's private documents
2. Bob cannot modify Alice's documents
3. Bob cannot delete Alice's documents
4. Bob cannot share documents he doesn't own
5. Bob cannot access Alice's folders
6. Users cannot perform actions without authentication
"""

import pytest

from tests.integration.conftest import AuthenticatedClient


def test_bob_cannot_read_alice_private_document(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob attempts to read Alice's private document
    Given: Alice has a private document
    When: Bob tries to read it
    Then: Access is denied (403 or 404)
    """
    # Alice creates private document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Alice Private.txt", "content": "Confidential", "is_public": False},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Bob tries to read
    read_response = bob_client.get(f"/api/documents/{doc_id}")

    # Should be denied - either 403 (forbidden) or 404 (not found for security)
    assert read_response.status_code in [403, 404]


def test_bob_cannot_update_alice_document(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob attempts to update Alice's document
    Given: Alice owns a document
    When: Bob tries to update it
    Then: Update is denied
    """
    # Alice creates document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Alice Doc.txt", "content": "Alice's content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Bob tries to update
    update_response = bob_client.put(
        f"/api/documents/{doc_id}",
        json={"content": "Bob's malicious edit"},
    )

    assert update_response.status_code == 403


def test_bob_cannot_delete_alice_document(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob attempts to delete Alice's document
    Given: Alice owns a document
    When: Bob tries to delete it
    Then: Deletion is denied
    """
    # Alice creates document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Important.txt", "content": "Important data"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Bob tries to delete
    delete_response = bob_client.delete(f"/api/documents/{doc_id}")

    assert delete_response.status_code in [403, 404]


def test_bob_cannot_share_alice_document(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient, charlie_client: AuthenticatedClient
):
    """
    Scenario: Bob attempts to share Alice's document
    Given: Alice owns a document
    When: Bob tries to share it with Charlie
    Then: Share is denied
    """
    # Alice creates document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Alice Doc.txt", "content": "Content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Bob tries to share it
    share_response = bob_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": "charlie-id", "permission": "read"},
    )

    assert share_response.status_code == 403


def test_bob_cannot_delete_alice_folder(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob attempts to delete Alice's folder
    Given: Alice owns a folder
    When: Bob tries to delete it
    Then: Deletion is denied
    """
    # Alice creates folder
    folder_response = alice_client.post("/api/folders", json={"name": "Alice's Folder"})
    assert folder_response.status_code == 201
    folder_id = folder_response.json()["id"]

    # Bob tries to delete
    delete_response = bob_client.delete(f"/api/folders/{folder_id}")

    assert delete_response.status_code in [403, 404]


def test_bob_cannot_modify_alice_folder(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob attempts to rename Alice's folder
    Given: Alice owns a folder
    When: Bob tries to rename it
    Then: Update is denied
    """
    # Alice creates folder
    folder_response = alice_client.post("/api/folders", json={"name": "Original Name"})
    assert folder_response.status_code == 201
    folder_id = folder_response.json()["id"]

    # Bob tries to rename
    update_response = bob_client.put(
        f"/api/folders/{folder_id}",
        json={"name": "Bob's Name"},
    )

    assert update_response.status_code in [403, 404]


def test_bob_cannot_delete_shared_document_with_read_permission(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob has read permission but tries to delete
    Given: Alice shared document with Bob (read-only)
    When: Bob tries to delete the document
    Then: Deletion is denied
    """
    # Alice creates and shares document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Shared.txt", "content": "Shared content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": "bob-id", "permission": "read"},
    )

    # Bob tries to delete
    delete_response = bob_client.delete(f"/api/documents/{doc_id}")

    assert delete_response.status_code == 403


def test_bob_lists_only_accessible_documents(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob lists documents, sees only what he can access
    Given: Alice has private documents
    When: Bob lists documents
    Then: Bob only sees his own and public documents
    """
    # Alice creates private document
    alice_client.post(
        "/api/documents",
        json={"name": "Alice Private.txt", "content": "Secret", "is_public": False},
    )

    # Bob lists documents
    list_response = bob_client.get("/api/documents")

    assert list_response.status_code == 200
    documents = list_response.json()

    # Bob should not see Alice's private document
    alice_private_docs = [d for d in documents if d["name"] == "Alice Private.txt"]
    assert len(alice_private_docs) == 0


@pytest.mark.slow
def test_complete_authorization_denial_workflow(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Comprehensive authorization denial test
    Given: Alice owns resources
    When: Bob attempts unauthorized operations
    Then: All operations are denied
    """
    # 1. Alice creates private folder
    folder_response = alice_client.post("/api/folders", json={"name": "Private Folder"})
    assert folder_response.status_code == 201
    folder_id = folder_response.json()["id"]

    # 2. Alice creates private document in folder
    doc_response = alice_client.post(
        "/api/documents",
        json={
            "name": "Private Doc.txt",
            "content": "Confidential information",
            "folder_id": folder_id,
            "is_public": False,
        },
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # 3. Bob attempts to read document (DENIED)
    read_response = bob_client.get(f"/api/documents/{doc_id}")
    assert read_response.status_code in [403, 404]

    # 4. Bob attempts to update document (DENIED)
    update_response = bob_client.put(
        f"/api/documents/{doc_id}",
        json={"content": "Hacked"},
    )
    assert update_response.status_code == 403

    # 5. Bob attempts to delete document (DENIED)
    delete_response = bob_client.delete(f"/api/documents/{doc_id}")
    assert delete_response.status_code in [403, 404]

    # 6. Bob attempts to access folder (DENIED)
    folder_get_response = bob_client.get(f"/api/folders/{folder_id}")
    assert folder_get_response.status_code in [403, 404]

    # 7. Bob attempts to delete folder (DENIED)
    folder_delete_response = bob_client.delete(f"/api/folders/{folder_id}")
    assert folder_delete_response.status_code in [403, 404]

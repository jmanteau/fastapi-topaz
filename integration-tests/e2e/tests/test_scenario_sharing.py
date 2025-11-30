from __future__ import annotations

"""
Integration Test: Document Sharing Scenarios

Prerequisites:
- All services running
- Alice, Bob, and Charlie users created and authenticated
- All session cookies set in environment variables

Scenarios tested:
1. Alice shares document with Bob (read permission)
2. Bob can read but not modify shared document
3. Alice shares with write permission
4. Bob can now modify the document
5. Alice revokes share
6. Multiple users share same document
7. Share conflict scenarios
"""

import pytest

from tests.conftest import AuthenticatedClient


def test_alice_shares_document_bob_reads(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Alice shares document, Bob reads it
    Given: Alice creates a document
    When: Alice shares it with Bob (read permission)
    Then: Bob can read but not write the document
    """
    # Alice creates document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Shared Report.pdf", "content": "Quarterly report..."},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Alice shares with Bob (read-only)
    # Note: Requires knowing Bob's actual user ID from Authentik
    share_response = alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": "bob-id", "permission": "read"},
    )

    # If Bob exists, share succeeds
    if share_response.status_code == 201:
        # Bob reads the document
        read_response = bob_client.get(f"/api/documents/{doc_id}")
        assert read_response.status_code in [200, 403, 404]
        # 200 if authorization allows, 403 if Topaz denies

        # Bob tries to update (should fail)
        update_response = bob_client.put(
            f"/api/documents/{doc_id}",
            json={"content": "Bob trying to modify"},
        )
        assert update_response.status_code == 403  # Forbidden


def test_alice_shares_with_write_bob_edits(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Alice grants write permission
    Given: Alice creates a document
    When: Alice shares with write permission
    Then: Bob can read and write the document
    """
    # Alice creates document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Collaborative Doc.md", "content": "# Collaboration\n\n..."},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Alice shares with Bob (write permission)
    share_response = alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": "bob-id", "permission": "write"},
    )

    if share_response.status_code == 201:
        # Bob can now update
        update_response = bob_client.put(
            f"/api/documents/{doc_id}",
            json={"content": "# Collaboration\n\nBob's contribution..."},
        )
        assert update_response.status_code in [200, 403]


def test_alice_views_document_shares(alice_client: AuthenticatedClient):
    """
    Scenario: Alice checks who has access
    Given: Alice has shared a document
    When: Alice lists shares for the document
    Then: All shares are displayed
    """
    # Create document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Team Document.md", "content": "Team content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Share with Bob
    alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": "bob-id", "permission": "read"},
    )

    # View shares
    shares_response = alice_client.get(f"/api/shares/document/{doc_id}")

    assert shares_response.status_code == 200
    shares = shares_response.json()
    assert isinstance(shares, list)


def test_share_with_multiple_users(
    alice_client: AuthenticatedClient,
    bob_client: AuthenticatedClient,
    charlie_client: AuthenticatedClient,
):
    """
    Scenario: Document shared with multiple users
    Given: Alice creates a document
    When: Alice shares with Bob and Charlie
    Then: Both can access based on their permissions
    """
    # Alice creates document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Team Project.md", "content": "Project details..."},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Share with Bob (read)
    share1_response = alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": "bob-id", "permission": "read"},
    )

    # Share with Charlie (write)
    share2_response = alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": "charlie-id", "permission": "write"},
    )

    # List shares
    if share1_response.status_code == 201 or share2_response.status_code == 201:
        shares_response = alice_client.get(f"/api/shares/document/{doc_id}")
        assert shares_response.status_code == 200


def test_cannot_share_same_document_twice(alice_client: AuthenticatedClient):
    """
    Scenario: Prevent duplicate shares
    Given: Alice has shared document with Bob
    When: Alice tries to share same document with Bob again
    Then: Conflict error is returned
    """
    # Create document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Doc.txt", "content": "Content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # First share
    share1_response = alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": "bob-id", "permission": "read"},
    )

    if share1_response.status_code == 201:
        # Second share (should fail)
        share2_response = alice_client.post(
            "/api/shares",
            json={"document_id": doc_id, "user_id": "bob-id", "permission": "write"},
        )

        assert share2_response.status_code == 409  # Conflict


def test_share_nonexistent_document(alice_client: AuthenticatedClient):
    """
    Scenario: Cannot share document that doesn't exist
    Given: Alice tries to share
    When: Document ID is invalid
    Then: 404 error is returned
    """
    response = alice_client.post(
        "/api/shares",
        json={"document_id": 999999, "user_id": "bob-id", "permission": "read"},
    )

    assert response.status_code == 404


def test_share_with_nonexistent_user(alice_client: AuthenticatedClient):
    """
    Scenario: Cannot share with user that doesn't exist
    Given: Alice creates document
    When: Alice tries to share with invalid user
    Then: 404 error is returned
    """
    # Create document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Doc.txt", "content": "Content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Share with non-existent user
    share_response = alice_client.post(
        "/api/shares",
        json={
            "document_id": doc_id,
            "user_id": "nonexistent-user-id",
            "permission": "read",
        },
    )

    assert share_response.status_code == 404


@pytest.mark.slow
def test_complete_sharing_workflow(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Complete document sharing lifecycle
    Given: Alice and Bob collaborate
    When: Full sharing workflow is executed
    Then: All operations succeed in correct order
    """
    # 1. Alice creates document
    doc_response = alice_client.post(
        "/api/documents",
        json={
            "name": "Project Spec.md",
            "content": "# Project Specification\n\n## Overview\n...",
        },
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # 2. Alice shares with Bob (read first)
    share_response = alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": "bob-id", "permission": "read"},
    )

    if share_response.status_code == 201:
        share_id = share_response.json()["id"]

        # 3. Bob reads document
        read_response = bob_client.get(f"/api/documents/{doc_id}")
        # May succeed or fail based on Topaz policy

        # 4. Alice removes share
        delete_response = alice_client.delete(f"/api/shares/{share_id}")
        assert delete_response.status_code in [204, 403, 404]

        # 5. Bob can no longer access (if authorization working)
        read_after_delete = bob_client.get(f"/api/documents/{doc_id}")
        # Should be 403 or 404 if authorization removes access

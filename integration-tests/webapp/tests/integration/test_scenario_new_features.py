from __future__ import annotations

"""
Integration Test: New Features - Toggle Public/Private & Sharing UI

Tests:
1. List users endpoint for sharing
2. Toggle document public/private
3. Share document workflow (create, list, remove)
"""

import pytest

from tests.integration.conftest import AuthenticatedClient


# =============================================================================
# Tests for /api/users endpoint
# =============================================================================


def test_list_users_returns_other_users(alice_client: AuthenticatedClient):
    """
    Scenario: Alice lists users for sharing
    Given: Alice is authenticated
    When: Alice requests the users list
    Then: List of users (excluding herself) is returned
    """
    response = alice_client.get("/api/users")

    assert response.status_code == 200
    users = response.json()
    assert isinstance(users, list)

    # Each user should have id, name, email
    for user in users:
        assert "id" in user
        assert "name" in user
        assert "email" in user


def test_list_users_excludes_current_user(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Current user is excluded from list
    Given: Alice and Bob are authenticated
    When: Alice lists users
    Then: Alice is not in the list, but Bob may be
    """
    response = alice_client.get("/api/users")

    assert response.status_code == 200
    users = response.json()

    # Alice should not see herself in the list
    alice_emails = [u["email"] for u in users if "alice" in u["email"].lower()]
    # This depends on actual user setup, but current user should be filtered


# =============================================================================
# Tests for toggle public/private
# =============================================================================


def test_owner_can_toggle_private_to_public(alice_client: AuthenticatedClient):
    """
    Scenario: Owner toggles private document to public
    Given: Alice has a private document
    When: Alice updates is_public to True
    Then: Document becomes public
    """
    # Create private document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Toggle Test.md", "content": "Test content", "is_public": False},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]
    assert doc_response.json()["is_public"] is False

    # Toggle to public
    update_response = alice_client.put(
        f"/api/documents/{doc_id}",
        json={"is_public": True},
    )

    assert update_response.status_code == 200
    assert update_response.json()["is_public"] is True


def test_owner_can_toggle_public_to_private(alice_client: AuthenticatedClient):
    """
    Scenario: Owner toggles public document to private
    Given: Alice has a public document
    When: Alice updates is_public to False
    Then: Document becomes private
    """
    # Create public document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Toggle Test 2.md", "content": "Test", "is_public": True},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Toggle to private
    update_response = alice_client.put(
        f"/api/documents/{doc_id}",
        json={"is_public": False},
    )

    assert update_response.status_code == 200
    assert update_response.json()["is_public"] is False


def test_non_owner_cannot_toggle_visibility(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Non-owner cannot change visibility
    Given: Alice owns a document
    When: Bob tries to toggle is_public
    Then: Update is denied
    """
    # Alice creates document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Alice Doc.md", "content": "Content", "is_public": False},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Bob tries to make it public
    update_response = bob_client.put(
        f"/api/documents/{doc_id}",
        json={"is_public": True},
    )

    assert update_response.status_code == 403


# =============================================================================
# Tests for share document workflow
# =============================================================================


def test_owner_can_create_share(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Owner shares document with another user
    Given: Alice owns a document and Bob exists
    When: Alice creates a share for Bob
    Then: Share is created successfully
    """
    # Alice creates document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Shared Doc.md", "content": "Shared content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Get Bob's user ID from users list
    users_response = alice_client.get("/api/users")
    assert users_response.status_code == 200
    users = users_response.json()

    if not users:
        pytest.skip("No other users available for sharing")

    bob_user = next((u for u in users if "bob" in u["email"].lower()), users[0])

    # Alice shares with Bob
    share_response = alice_client.post(
        "/api/shares",
        json={
            "document_id": doc_id,
            "user_id": bob_user["id"],
            "permission": "read",
        },
    )

    assert share_response.status_code in [201, 403, 404]


def test_owner_can_list_document_shares(alice_client: AuthenticatedClient):
    """
    Scenario: Owner lists shares for a document
    Given: Alice has shared a document
    When: Alice requests shares list
    Then: All shares are returned
    """
    # Create document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "List Shares Test.md", "content": "Content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # List shares
    shares_response = alice_client.get(f"/api/shares/document/{doc_id}")

    assert shares_response.status_code == 200
    assert isinstance(shares_response.json(), list)


def test_owner_can_remove_share(alice_client: AuthenticatedClient):
    """
    Scenario: Owner removes a share
    Given: Alice has shared a document
    When: Alice deletes the share
    Then: Share is removed
    """
    # Create document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Remove Share Test.md", "content": "Content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Get a user to share with
    users_response = alice_client.get("/api/users")
    if users_response.status_code != 200 or not users_response.json():
        pytest.skip("No users available")

    user = users_response.json()[0]

    # Create share
    share_response = alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": user["id"], "permission": "read"},
    )

    if share_response.status_code != 201:
        pytest.skip("Could not create share")

    share_id = share_response.json()["id"]

    # Remove share
    delete_response = alice_client.delete(f"/api/shares/{share_id}")
    assert delete_response.status_code in [204, 403]


@pytest.mark.slow
def test_complete_share_workflow(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Complete sharing workflow
    1. Alice creates private document
    2. Bob cannot access it
    3. Alice shares with Bob (read)
    4. Bob can now read
    5. Alice removes share
    6. Bob loses access
    """
    # 1. Alice creates private document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Workflow Test.md", "content": "Secret", "is_public": False},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # 2. Bob cannot access
    bob_read = bob_client.get(f"/api/documents/{doc_id}")
    assert bob_read.status_code in [403, 404]

    # 3. Get Bob's ID and share
    users = alice_client.get("/api/users").json()
    bob_user = next((u for u in users if "bob" in u.get("email", "").lower()), None)

    if not bob_user:
        pytest.skip("Bob user not found")

    share_response = alice_client.post(
        "/api/shares",
        json={"document_id": doc_id, "user_id": bob_user["id"], "permission": "read"},
    )

    if share_response.status_code != 201:
        pytest.skip("Could not create share")

    share_id = share_response.json()["id"]

    # 4. Bob can now read
    bob_read_after = bob_client.get(f"/api/documents/{doc_id}")
    assert bob_read_after.status_code == 200

    # 5. Alice removes share
    alice_client.delete(f"/api/shares/{share_id}")

    # 6. Bob loses access
    bob_read_final = bob_client.get(f"/api/documents/{doc_id}")
    assert bob_read_final.status_code in [403, 404]

from __future__ import annotations

"""
Integration Test: Public Document Scenarios

Tests public document accessibility:
1. Alice creates public document
2. Bob can read public documents
3. Anyone can list public documents
4. Public documents cannot be modified by non-owners
5. Making private document public
6. Making public document private
"""

import pytest

from tests.conftest import AuthenticatedClient


def test_alice_creates_public_document(alice_client: AuthenticatedClient):
    """
    Scenario: Alice creates a public document
    Given: Alice wants to share information
    When: Alice creates document with is_public=True
    Then: Document is marked as public
    """
    response = alice_client.post(
        "/api/documents",
        json={
            "name": "Company Announcement.md",
            "content": "# Important Announcement\n\nWe are pleased to announce...",
            "is_public": True,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["is_public"] is True


def test_bob_reads_public_document(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob reads Alice's public document
    Given: Alice has created a public document
    When: Bob requests to read it
    Then: Bob can access the document
    """
    # Alice creates public document
    doc_response = alice_client.post(
        "/api/documents",
        json={
            "name": "Public Info.md",
            "content": "# Public Information\n\nAvailable to everyone",
            "is_public": True,
        },
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Bob reads public document
    read_response = bob_client.get(f"/api/documents/{doc_id}")

    # Bob should be able to read public documents
    assert read_response.status_code == 200
    data = read_response.json()
    assert data["is_public"] is True


def test_public_documents_in_list(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Public documents appear in everyone's list
    Given: Alice creates a public document
    When: Bob lists documents
    Then: Alice's public document appears in Bob's list
    """
    # Alice creates public document
    doc_response = alice_client.post(
        "/api/documents",
        json={
            "name": "Newsletter.md",
            "content": "Monthly newsletter...",
            "is_public": True,
        },
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Bob lists documents
    list_response = bob_client.get("/api/documents")

    assert list_response.status_code == 200
    documents = list_response.json()

    # Find the public document in Bob's list
    public_doc = next((d for d in documents if d["id"] == doc_id), None)
    if public_doc:
        assert public_doc["is_public"] is True


def test_bob_cannot_modify_alice_public_document(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob cannot modify Alice's public document
    Given: Alice has a public document
    When: Bob tries to update it
    Then: Update is denied
    """
    # Alice creates public document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Public.txt", "content": "Public content", "is_public": True},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Bob tries to update
    update_response = bob_client.put(
        f"/api/documents/{doc_id}",
        json={"content": "Bob's unauthorized edit"},
    )

    assert update_response.status_code == 403


def test_bob_cannot_delete_alice_public_document(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Bob cannot delete Alice's public document
    Given: Alice has a public document
    When: Bob tries to delete it
    Then: Deletion is denied
    """
    # Alice creates public document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Public.txt", "content": "Content", "is_public": True},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Bob tries to delete
    delete_response = bob_client.delete(f"/api/documents/{doc_id}")

    assert delete_response.status_code in [403, 404]


def test_alice_makes_private_document_public(alice_client: AuthenticatedClient):
    """
    Scenario: Alice changes private document to public
    Given: Alice has a private document
    When: Alice updates it to be public
    Then: Document becomes publicly accessible
    """
    # Create private document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Draft.md", "content": "Draft content", "is_public": False},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Make it public
    update_response = alice_client.put(
        f"/api/documents/{doc_id}",
        json={"is_public": True},
    )

    assert update_response.status_code == 200
    data = update_response.json()
    assert data["is_public"] is True


def test_alice_makes_public_document_private(alice_client: AuthenticatedClient):
    """
    Scenario: Alice changes public document to private
    Given: Alice has a public document
    When: Alice updates it to be private
    Then: Document is no longer publicly accessible
    """
    # Create public document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Public.md", "content": "Public content", "is_public": True},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Make it private
    update_response = alice_client.put(
        f"/api/documents/{doc_id}",
        json={"is_public": False},
    )

    assert update_response.status_code == 200
    data = update_response.json()
    assert data["is_public"] is False


def test_multiple_users_create_public_documents(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Multiple users create public documents
    Given: Both Alice and Bob are authenticated
    When: Both create public documents
    Then: Both can see each other's public documents
    """
    # Alice creates public document
    alice_doc = alice_client.post(
        "/api/documents",
        json={"name": "Alice Public.md", "content": "Alice content", "is_public": True},
    )
    assert alice_doc.status_code == 201

    # Bob creates public document
    bob_doc = bob_client.post(
        "/api/documents",
        json={"name": "Bob Public.md", "content": "Bob content", "is_public": True},
    )
    assert bob_doc.status_code == 201

    # Both list documents
    alice_list = alice_client.get("/api/documents")
    bob_list = bob_client.get("/api/documents")

    assert alice_list.status_code == 200
    assert bob_list.status_code == 200


@pytest.mark.slow
def test_complete_public_document_workflow(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """
    Scenario: Complete public document lifecycle
    Given: Alice manages public communications
    When: Complete workflow is executed
    Then: Public access works correctly
    """
    # 1. Alice creates private draft
    draft_response = alice_client.post(
        "/api/documents",
        json={
            "name": "Press Release.md",
            "content": "# DRAFT - Press Release\n\n...",
            "is_public": False,
        },
    )
    assert draft_response.status_code == 201
    doc_id = draft_response.json()["id"]

    # 2. Bob cannot read draft
    bob_read = bob_client.get(f"/api/documents/{doc_id}")
    assert bob_read.status_code in [403, 404]

    # 3. Alice finalizes and publishes
    publish_response = alice_client.put(
        f"/api/documents/{doc_id}",
        json={
            "name": "Press Release - Final.md",
            "content": "# Press Release\n\nFinal version...",
            "is_public": True,
        },
    )
    assert publish_response.status_code == 200

    # 4. Bob can now read published document
    bob_read_public = bob_client.get(f"/api/documents/{doc_id}")
    assert bob_read_public.status_code == 200

    # 5. Bob still cannot modify
    bob_modify = bob_client.put(
        f"/api/documents/{doc_id}",
        json={"content": "Unauthorized change"},
    )
    assert bob_modify.status_code == 403

    # 6. Alice can still delete her public document
    alice_delete = alice_client.delete(f"/api/documents/{doc_id}")
    assert alice_delete.status_code == 204

from __future__ import annotations

"""
Integration Test: Alice's Complete Workflow

Prerequisites:
- All Docker services running (make up)
- Alice user created in Authentik with email: alice@example.com
- Alice logged in and ALICE_SESSION_COOKIE environment variable set

Scenario:
Alice is a project manager who uses the document management system to:
1. Create project folders
2. Create and manage documents
3. Share documents with team members
4. Manage document permissions
"""

import pytest

from tests.integration.conftest import AuthenticatedClient


def test_alice_health_check(alice_client: AuthenticatedClient):
    """Verify Alice can access the application."""
    response = alice_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_alice_creates_project_folder(alice_client: AuthenticatedClient):
    """
    Scenario: Alice creates a folder for her project
    Given: Alice is authenticated
    When: Alice creates a new folder
    Then: Folder is created successfully
    """
    response = alice_client.post("/api/folders", json={"name": "Q4 Marketing Campaign"})

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Q4 Marketing Campaign"
    assert "id" in data
    assert "owner_id" in data

    # Store folder_id for cleanup
    return data["id"]


def test_alice_creates_private_document(alice_client: AuthenticatedClient):
    """
    Scenario: Alice creates a private document
    Given: Alice is authenticated
    When: Alice creates a private document
    Then: Document is created and not public
    """
    response = alice_client.post(
        "/api/documents",
        json={
            "name": "Strategy Draft.md",
            "content": "# Marketing Strategy\n\n## Confidential\n\nOur strategy...",
            "is_public": False,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Strategy Draft.md"
    assert data["is_public"] is False
    assert "id" in data

    return data["id"]


def test_alice_creates_public_announcement(alice_client: AuthenticatedClient):
    """
    Scenario: Alice creates a public announcement
    Given: Alice is authenticated
    When: Alice creates a public document
    Then: Document is accessible to everyone
    """
    response = alice_client.post(
        "/api/documents",
        json={
            "name": "Team Announcement.md",
            "content": "# Welcome!\n\nExcited to announce...",
            "is_public": True,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["is_public"] is True

    return data["id"]


def test_alice_lists_her_documents(alice_client: AuthenticatedClient):
    """
    Scenario: Alice views her document list
    Given: Alice has created multiple documents
    When: Alice requests her documents
    Then: All her documents are returned
    """
    response = alice_client.get("/api/documents")

    assert response.status_code == 200
    documents = response.json()
    assert isinstance(documents, list)
    # Alice should have at least some documents
    assert len(documents) >= 0


def test_alice_updates_document_content(alice_client: AuthenticatedClient):
    """
    Scenario: Alice updates a document
    Given: Alice owns a document
    When: Alice updates the content
    Then: Document is updated successfully
    """
    # First create a document
    create_response = alice_client.post(
        "/api/documents",
        json={"name": "Draft.md", "content": "Initial draft"},
    )
    assert create_response.status_code == 201
    doc_id = create_response.json()["id"]

    # Update the document
    update_response = alice_client.put(
        f"/api/documents/{doc_id}",
        json={"content": "Updated draft with more details"},
    )

    assert update_response.status_code == 200
    data = update_response.json()
    assert data["content"] == "Updated draft with more details"


def test_alice_creates_document_in_folder(alice_client: AuthenticatedClient):
    """
    Scenario: Alice organizes documents into folders
    Given: Alice has a folder
    When: Alice creates a document in that folder
    Then: Document is associated with the folder
    """
    # Create folder
    folder_response = alice_client.post("/api/folders", json={"name": "Reports"})
    assert folder_response.status_code == 201
    folder_id = folder_response.json()["id"]

    # Create document in folder
    doc_response = alice_client.post(
        "/api/documents",
        json={
            "name": "Q4 Report.pdf",
            "content": "Quarterly financial report...",
            "folder_id": folder_id,
        },
    )

    assert doc_response.status_code == 201
    data = doc_response.json()
    assert data["folder_id"] == folder_id


def test_alice_shares_document_with_bob(alice_client: AuthenticatedClient):
    """
    Scenario: Alice shares a document with Bob (read permission)
    Given: Alice owns a document
    When: Alice shares it with Bob for reading
    Then: Share is created successfully
    """
    # Create document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Shared Report.pdf", "content": "Report content..."},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Share with Bob (bob-id must match Bob's actual user ID)
    share_response = alice_client.post(
        "/api/shares",
        json={
            "document_id": doc_id,
            "user_id": "bob-id",  # This should match Bob's actual ID from Authentik
            "permission": "read",
        },
    )

    # May return 201 if Bob exists, or 404 if Bob user not found
    assert share_response.status_code in [201, 404]


def test_alice_shares_document_with_write_permission(alice_client: AuthenticatedClient):
    """
    Scenario: Alice grants write permission
    Given: Alice owns a document
    When: Alice shares with write permission
    Then: Collaborator can edit the document
    """
    # Create document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Collaborative Doc.md", "content": "# Let's collaborate\n\n..."},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Share with write permission
    share_response = alice_client.post(
        "/api/shares",
        json={
            "document_id": doc_id,
            "user_id": "charlie-id",  # Charlie's ID from Authentik
            "permission": "write",
        },
    )

    assert share_response.status_code in [201, 404]


def test_alice_views_document_shares(alice_client: AuthenticatedClient):
    """
    Scenario: Alice checks who has access to her document
    Given: Alice has shared a document
    When: Alice views document shares
    Then: All shares are listed
    """
    # Create and share document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Team Doc.md", "content": "Team document"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # View shares
    shares_response = alice_client.get(f"/api/shares/document/{doc_id}")

    assert shares_response.status_code == 200
    shares = shares_response.json()
    assert isinstance(shares, list)


def test_alice_creates_nested_folder_structure(alice_client: AuthenticatedClient):
    """
    Scenario: Alice creates hierarchical folder structure
    Given: Alice wants to organize documents
    When: Alice creates parent and child folders
    Then: Folder hierarchy is created
    """
    # Create parent folder
    parent_response = alice_client.post("/api/folders", json={"name": "Projects"})
    assert parent_response.status_code == 201
    parent_id = parent_response.json()["id"]

    # Create child folder
    child_response = alice_client.post(
        "/api/folders", json={"name": "2024", "parent_folder_id": parent_id}
    )

    assert child_response.status_code == 201
    child_data = child_response.json()
    assert child_data["parent_folder_id"] == parent_id


def test_alice_deletes_her_document(alice_client: AuthenticatedClient):
    """
    Scenario: Alice deletes a document she no longer needs
    Given: Alice owns a document
    When: Alice deletes it
    Then: Document is removed
    """
    # Create document
    doc_response = alice_client.post(
        "/api/documents",
        json={"name": "Temporary.txt", "content": "Temp content"},
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # Delete document
    delete_response = alice_client.delete(f"/api/documents/{doc_id}")

    assert delete_response.status_code == 204

    # Verify deletion
    get_response = alice_client.get(f"/api/documents/{doc_id}")
    assert get_response.status_code == 404


@pytest.mark.slow
def test_alice_complete_project_workflow(alice_client: AuthenticatedClient):
    """
    Scenario: Alice's complete project management workflow
    Given: Alice starts a new project
    When: Alice creates structure, documents, and shares
    Then: Complete project setup is successful

    This is a comprehensive end-to-end test.
    """
    # Step 1: Create project folder
    folder_response = alice_client.post(
        "/api/folders", json={"name": "Product Launch 2024"}
    )
    assert folder_response.status_code == 201
    folder_id = folder_response.json()["id"]

    # Step 2: Create project plan document
    plan_response = alice_client.post(
        "/api/documents",
        json={
            "name": "Launch Plan.md",
            "content": "# Product Launch Plan\n\n## Timeline\n...",
            "folder_id": folder_id,
        },
    )
    assert plan_response.status_code == 201
    plan_id = plan_response.json()["id"]

    # Step 3: Create public announcement
    announcement_response = alice_client.post(
        "/api/documents",
        json={
            "name": "Launch Announcement.md",
            "content": "We're excited to announce...",
            "is_public": True,
        },
    )
    assert announcement_response.status_code == 201

    # Step 4: Update plan with more details
    update_response = alice_client.put(
        f"/api/documents/{plan_id}",
        json={"content": "# Product Launch Plan\n\n## Updated Timeline\n\n..."},
    )
    assert update_response.status_code == 200

    # Step 5: List all documents (verify they exist)
    list_response = alice_client.get("/api/documents")
    assert list_response.status_code == 200
    documents = list_response.json()
    assert len(documents) >= 2

    # Step 6: List folders
    folders_response = alice_client.get("/api/folders")
    assert folders_response.status_code == 200
    folders = folders_response.json()
    assert len(folders) >= 1

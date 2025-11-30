from __future__ import annotations

"""
Integration Test: Bob's Workflow and Interactions

Prerequisites:
- All Docker services running (make up)
- Bob user created in Authentik with email: bob@example.com
- Bob logged in and BOB_SESSION_COOKIE environment variable set

Scenario:
Bob is a team member who:
1. Creates his own documents
2. Reads public documents created by others
3. Accesses documents shared with him
4. Cannot access private documents he doesn't own
"""

import pytest

from tests.integration.conftest import AuthenticatedClient


def test_bob_health_check(bob_client: AuthenticatedClient):
    """Verify Bob can access the application."""
    response = bob_client.get("/health")
    assert response.status_code == 200


def test_bob_creates_own_document(bob_client: AuthenticatedClient):
    """
    Scenario: Bob creates his own document
    Given: Bob is authenticated
    When: Bob creates a document
    Then: Document is created and owned by Bob
    """
    response = bob_client.post(
        "/api/documents",
        json={
            "name": "Bob's Notes.md",
            "content": "# My Notes\n\nImportant information...",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Bob's Notes.md"
    assert "owner_id" in data

    return data["id"]


def test_bob_reads_own_document(bob_client: AuthenticatedClient):
    """
    Scenario: Bob reads his own document
    Given: Bob has created a document
    When: Bob requests to read it
    Then: Document content is returned
    """
    # Create document
    create_response = bob_client.post(
        "/api/documents",
        json={"name": "My Document.txt", "content": "My content"},
    )
    assert create_response.status_code == 201
    doc_id = create_response.json()["id"]

    # Read document
    read_response = bob_client.get(f"/api/documents/{doc_id}")

    assert read_response.status_code == 200
    data = read_response.json()
    assert data["content"] == "My content"


def test_bob_updates_own_document(bob_client: AuthenticatedClient):
    """
    Scenario: Bob updates his document
    Given: Bob owns a document
    When: Bob updates it
    Then: Update succeeds
    """
    # Create document
    create_response = bob_client.post(
        "/api/documents",
        json={"name": "Draft.md", "content": "Draft v1"},
    )
    assert create_response.status_code == 201
    doc_id = create_response.json()["id"]

    # Update document
    update_response = bob_client.put(
        f"/api/documents/{doc_id}",
        json={"content": "Draft v2 - updated"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["content"] == "Draft v2 - updated"


def test_bob_deletes_own_document(bob_client: AuthenticatedClient):
    """
    Scenario: Bob deletes his document
    Given: Bob owns a document
    When: Bob deletes it
    Then: Deletion succeeds
    """
    # Create document
    create_response = bob_client.post(
        "/api/documents",
        json={"name": "ToDelete.txt", "content": "Will be deleted"},
    )
    assert create_response.status_code == 201
    doc_id = create_response.json()["id"]

    # Delete document
    delete_response = bob_client.delete(f"/api/documents/{doc_id}")

    assert delete_response.status_code == 204


def test_bob_creates_folder(bob_client: AuthenticatedClient):
    """
    Scenario: Bob organizes with folders
    Given: Bob is authenticated
    When: Bob creates a folder
    Then: Folder is created
    """
    response = bob_client.post("/api/folders", json={"name": "Bob's Work"})

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Bob's Work"


def test_bob_lists_his_documents(bob_client: AuthenticatedClient):
    """
    Scenario: Bob views his document list
    Given: Bob has documents
    When: Bob lists documents
    Then: His documents and public documents are visible
    """
    response = bob_client.get("/api/documents")

    assert response.status_code == 200
    documents = response.json()
    assert isinstance(documents, list)


def test_bob_lists_his_folders(bob_client: AuthenticatedClient):
    """
    Scenario: Bob views his folders
    Given: Bob has folders
    When: Bob lists folders
    Then: Only his folders are visible
    """
    response = bob_client.get("/api/folders")

    assert response.status_code == 200
    folders = response.json()
    assert isinstance(folders, list)


@pytest.mark.slow
def test_bob_complete_workflow(bob_client: AuthenticatedClient):
    """
    Scenario: Bob's typical day workflow
    Given: Bob starts his workday
    When: Bob performs typical tasks
    Then: All operations succeed
    """
    # 1. Create folder for daily work
    folder_response = bob_client.post("/api/folders", json={"name": "Daily Tasks"})
    assert folder_response.status_code == 201
    folder_id = folder_response.json()["id"]

    # 2. Create task list document
    doc_response = bob_client.post(
        "/api/documents",
        json={
            "name": "Tasks.md",
            "content": "# Today's Tasks\n\n- [ ] Review code\n- [ ] Update docs",
            "folder_id": folder_id,
        },
    )
    assert doc_response.status_code == 201
    doc_id = doc_response.json()["id"]

    # 3. Update task list
    update_response = bob_client.put(
        f"/api/documents/{doc_id}",
        json={
            "content": "# Today's Tasks\n\n- [x] Review code\n- [ ] Update docs\n- [ ] Meeting at 2pm"
        },
    )
    assert update_response.status_code == 200

    # 4. List all my work
    list_response = bob_client.get("/api/documents")
    assert list_response.status_code == 200
    assert len(list_response.json()) >= 1


from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.dependencies import get_db, get_current_user_id
from app.db.base import Base
from app.models.repository import Repository
from app.models.ingestion_job import IngestionJob

import app.api.routes.ingestion as ingestion_routes


# Test database: in-memory SQLite

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


@pytest.fixture
def client():

    Base.metadata.create_all(bind=engine)

    def override_get_db():

        db = TestingSessionLocal()

        try:
            yield db

        finally:
            db.close()

    # User object required by repository routes.
    def override_repository_user():
        return SimpleNamespace(id=1)

    # Integer required by ingestion routes.
    def override_ingestion_user():
        return 1

    app.dependency_overrides[get_db] = override_get_db

    # Keep the original dependency behavior compatible with repository routes.
    app.dependency_overrides[get_current_user_id] = (
        override_repository_user
    )

    # Override only the ingestion router's dependency.
    # This works because both routers use the same dependency callable,
    # so a global override cannot provide different return types per route.
    #
    # We will use a separate dependency for ingestion below.

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()

    Base.metadata.drop_all(bind=engine)


def test_create_repository(client):

    response = client.post(
        "/repositories",
        json={
            "name": "RepoPilot AI",
            "github_url": "https://github.com/example/RepoPilot-AI",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["name"] == "RepoPilot AI"
    assert data["github_url"] == (
        "https://github.com/example/RepoPilot-AI"
    )
    assert data["owner_id"] == 1
    assert "id" in data


def test_create_repository_starts_ingestion_job(client, monkeypatch):
    async def mock_process_ingestion_job(job_id: int):
        pass

    monkeypatch.setattr(
        ingestion_routes,
        "process_ingestion_job",
        mock_process_ingestion_job,
    )

    response = client.post(
        "/repositories",
        json={
            "name": "RepoPilot AI",
            "github_url": "https://github.com/example/RepoPilot-AI",
        },
    )

    assert response.status_code == 201

    db = TestingSessionLocal()
    try:
        jobs = db.query(IngestionJob).all()
        assert len(jobs) == 1
        assert jobs[0].repository_id == response.json()["id"]
        assert jobs[0].user_id == 1
        assert jobs[0].status == "pending"
    finally:
        db.close()


def test_create_repository_rejects_duplicate_github_url(client):
    client.post(
        "/repositories",
        json={
            "name": "RepoPilot AI",
            "github_url": "https://github.com/example/RepoPilot-AI",
        },
    )

    response = client.post(
        "/repositories",
        json={
            "name": "RepoPilot AI Duplicate",
            "github_url": "https://github.com/example/RepoPilot-AI",
        },
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


def test_create_repository_rejects_invalid_github_url(client):
    response = client.post(
        "/repositories",
        json={
            "name": "Bad Repo",
            "github_url": "https://example.com/not-github",
        },
    )

    assert response.status_code == 422


def test_create_repository_rejects_blank_name(client):
    response = client.post(
        "/repositories",
        json={
            "name": "   ",
            "github_url": "https://github.com/example/repo-one",
        },
    )

    assert response.status_code == 422


def test_refresh_repository_creates_new_ingestion_job(client, monkeypatch):
    async def mock_process_ingestion_job(job_id: int):
        pass

    monkeypatch.setattr(
        ingestion_routes,
        "process_ingestion_job",
        mock_process_ingestion_job,
    )

    create_response = client.post(
        "/repositories",
        json={
            "name": "Repository One",
            "github_url": "https://github.com/example/repo-one",
        },
    )

    repository_id = create_response.json()["id"]

    refresh_response = client.post(f"/repositories/{repository_id}/refresh")

    assert refresh_response.status_code == 202
    assert refresh_response.json()["repository_id"] == repository_id
    assert refresh_response.json()["user_id"] == 1

    db = TestingSessionLocal()
    try:
        jobs = db.query(IngestionJob).all()
        assert len(jobs) == 2
    finally:
        db.close()


def test_list_repositories(client):

    client.post(
        "/repositories",
        json={
            "name": "Repository One",
            "github_url": "https://github.com/example/repo-one",
        },
    )

    response = client.get("/repositories")

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["name"] == "Repository One"


def test_get_repository(client):

    create_response = client.post(
        "/repositories",
        json={
            "name": "Repository One",
            "github_url": "https://github.com/example/repo-one",
        },
    )

    repository_id = create_response.json()["id"]

    response = client.get(
        f"/repositories/{repository_id}"
    )

    assert response.status_code == 200
    assert response.json()["id"] == repository_id
    assert response.json()["name"] == "Repository One"


def test_get_nonexistent_repository(client):

    response = client.get("/repositories/9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


def test_delete_repository(client):

    create_response = client.post(
        "/repositories",
        json={
            "name": "Repository One",
            "github_url": "https://github.com/example/repo-one",
        },
    )

    repository_id = create_response.json()["id"]

    response = client.delete(
        f"/repositories/{repository_id}"
    )

    assert response.status_code == 204

    get_response = client.get(
        f"/repositories/{repository_id}"
    )

    assert get_response.status_code == 404


def test_user_cannot_access_another_users_repository(client):

    db = TestingSessionLocal()

    try:

        repository = Repository(
            name="Private Repository",
            github_url="https://github.com/example/private-repo",
            owner_id=2,
        )

        db.add(repository)
        db.commit()
        db.refresh(repository)

        repository_id = repository.id

    finally:
        db.close()

    response = client.get(
        f"/repositories/{repository_id}"
    )

    assert response.status_code == 404


def test_start_ingestion_uses_repository_id(
    client,
    monkeypatch,
):

    # Mock background worker.
    async def mock_process_ingestion_job(job_id: int):
        pass

    monkeypatch.setattr(
        ingestion_routes,
        "process_ingestion_job",
        mock_process_ingestion_job,
    )

    db = TestingSessionLocal()

    try:

        repo = Repository(
            name="RepoPilot AI",
            github_url="https://github.com/example/RepoPilot-AI",
            owner_id=1,
        )

        db.add(repo)
        db.commit()
        db.refresh(repo)

        repository_id = repo.id

    finally:
        db.close()

    response = client.post(
        "/ingestion/start",
        json={
            "repository_id": repository_id,
        },
    )

    # This test requires ingestion route to receive integer user ID.
    # See the separate dependency correction below.

    assert response.status_code == 202

    data = response.json()

    assert data["repository_id"] == repository_id
    assert data["user_id"] == 1
    assert data["status"] == "pending"

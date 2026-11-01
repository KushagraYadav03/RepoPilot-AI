
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.dependencies import get_db, get_current_user_id
from app.db.base import Base
from app.models.user import User
from app.models.repository import Repository


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

    # Routes expect current_user.id, so provide a user-like object.
    def override_get_current_user_id():
        return SimpleNamespace(id=1)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = (
        override_get_current_user_id
    )

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

    response = client.get(f"/repositories/{repository_id}")

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

    response = client.delete(f"/repositories/{repository_id}")

    assert response.status_code == 204

    get_response = client.get(f"/repositories/{repository_id}")
    assert get_response.status_code == 404


def test_user_cannot_access_another_users_repository(client):
    # Insert a repository owned by user 2.
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

    # The authenticated test user has ID 1.
    response = client.get(f"/repositories/{repository_id}")

    assert response.status_code == 404

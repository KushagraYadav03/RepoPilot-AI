
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.base import Base
from app.core.dependencies import get_db


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    Base.metadata.create_all(bind=engine)

    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False
    )

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_register(client):
    response = client.post(
        "/register",
        json={
            "name": "Kushagra",
            "email": "kushagra@example.com",
            "password": "Password@123"
        }
    )

    assert response.status_code == 201
    assert response.json()["email"] == "kushagra@example.com"
    assert "password" not in response.json()


def test_duplicate_registration(client):
    data = {
        "name": "Kushagra",
        "email": "kushagra@example.com",
        "password": "Password@123"
    }

    client.post("/register", json=data)
    response = client.post("/register", json=data)

    assert response.status_code == 400


def test_login(client):
    client.post(
        "/register",
        json={
            "name": "Kushagra",
            "email": "kushagra@example.com",
            "password": "Password@123"
        }
    )

    response = client.post(
        "/login",
        json={
            "email": "kushagra@example.com",
            "password": "Password@123"
        }
    )

    assert response.status_code == 200
    assert "access_token" in response.json()


def test_wrong_password(client):
    client.post(
        "/register",
        json={
            "name": "Kushagra",
            "email": "kushagra@example.com",
            "password": "Password@123"
        }
    )

    response = client.post(
        "/login",
        json={
            "email": "kushagra@example.com",
            "password": "WrongPassword"
        }
    )

    assert response.status_code == 401


def test_users_me(client):
    client.post(
        "/register",
        json={
            "name": "Kushagra",
            "email": "kushagra@example.com",
            "password": "Password@123"
        }
    )

    login_response = client.post(
        "/login",
        json={
            "email": "kushagra@example.com",
            "password": "Password@123"
        }
    )

    assert login_response.status_code == 200, login_response.json()

    token = login_response.json()["access_token"]

    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200, response.json()
    assert response.json()["name"] == "Kushagra"


def test_users_me_without_token(client):
    response = client.get("/users/me")

    assert response.status_code == 401

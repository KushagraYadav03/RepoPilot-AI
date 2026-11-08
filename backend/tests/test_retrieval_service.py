from types import SimpleNamespace

import pytest

from app.services import retrieval_service


def make_point(
    point_id,
    file_path,
    symbol_name,
    content,
    score=0.9,
):
    return SimpleNamespace(
        id=point_id,
        score=score,
        payload={
            "file_path": file_path,
            "symbol_name": symbol_name,
            "symbol_kind": "function",
            "start_line": 10,
            "end_line": 25,
            "content": content,
            "commit_sha": "abc123",
        },
    )


def test_retrieve_repository_chunks(monkeypatch):

    monkeypatch.setattr(
        retrieval_service,
        "embed_query",
        lambda query: [0.1, 0.2, 0.3],
    )

    monkeypatch.setattr(
        retrieval_service,
        "query_repository_embeddings",
        lambda **kwargs: [
            make_point(
                "point-1",
                "app/auth.py",
                "create_access_token",
                "Generate JWT access token",
            ),
            make_point(
                "point-2",
                "app/security.py",
                "verify_token",
                "Verify JWT token",
                0.85,
            ),
        ],
    )

    results = retrieval_service.retrieve_repository_chunks(
        repository_id=1,
        query="Where is JWT authentication implemented?",
        limit=5,
    )

    assert len(results) == 2

    assert results[0]["file_path"] == "app/auth.py"

    assert results[0]["symbol_name"] == (
        "create_access_token"
    )

    assert results[0]["repository_id"] == 1

    assert results[0]["score"] == 0.9


def test_duplicate_results_are_removed(monkeypatch):

    monkeypatch.setattr(
        retrieval_service,
        "embed_query",
        lambda query: [0.1, 0.2],
    )

    duplicate_points = [
        make_point(
            "point-1",
            "app/auth.py",
            "create_token",
            "Generate token",
        ),
        make_point(
            "point-2",
            "app/auth.py",
            "create_token",
            "Generate token",
        ),
    ]

    monkeypatch.setattr(
        retrieval_service,
        "query_repository_embeddings",
        lambda **kwargs: duplicate_points,
    )

    results = retrieval_service.retrieve_repository_chunks(
        repository_id=1,
        query="JWT token",
    )

    assert len(results) == 1


def test_repository_filter_is_passed(monkeypatch):

    monkeypatch.setattr(
        retrieval_service,
        "embed_query",
        lambda query: [0.1, 0.2],
    )

    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        retrieval_service,
        "query_repository_embeddings",
        fake_search,
    )

    retrieval_service.retrieve_repository_chunks(
        repository_id=42,
        query="Find database connection",
        limit=3,
        score_threshold=0.7,
    )

    assert captured["repository_id"] == 42
    assert captured["limit"] == 3
    assert captured["score_threshold"] == 0.7


def test_empty_query_raises_error():

    with pytest.raises(ValueError):

        retrieval_service.retrieve_repository_chunks(
            repository_id=1,
            query=" ",
        )


def test_invalid_repository_id_raises_error():

    with pytest.raises(ValueError):

        retrieval_service.retrieve_repository_chunks(
            repository_id=0,
            query="Find authentication",
        )


def test_invalid_limit_raises_error():

    with pytest.raises(ValueError):

        retrieval_service.retrieve_repository_chunks(
            repository_id=1,
            query="Find authentication",
            limit=0,
        )


def test_empty_embedding_raises_error(monkeypatch):

    monkeypatch.setattr(
        retrieval_service,
        "embed_query",
        lambda query: [],
    )

    with pytest.raises(ValueError):

        retrieval_service.retrieve_repository_chunks(
            repository_id=1,
            query="Find authentication",
        )
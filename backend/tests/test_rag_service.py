
from types import SimpleNamespace

import pytest

from app.services import rag_service


def make_chunk():
    return {
        "id": "point-1",
        "repository_id": 1,
        "file_path": "app/core/security.py",
        "symbol_name": "create_access_token",
        "symbol_kind": "function",
        "start_line": 10,
        "end_line": 25,
        "content": "def create_access_token(data):\n    return token",
        "commit_sha": "abc123def456",
        "score": 0.91,
    }


class FakeProvider:

    async def generate(
        self,
        prompt,
        system_instruction=None,
        temperature=0.2,
        max_output_tokens=2048,
    ):
        assert "S1" in prompt
        assert "app/core/security.py" in prompt
        assert system_instruction is not None

        return SimpleNamespace(
            text="JWT authentication is implemented in security.py [S1].",
            provider="gemini",
            model="test-model",
        )


@pytest.mark.asyncio
async def test_answer_returns_citation_metadata(monkeypatch):

    retrieved_chunks = [make_chunk()]

    monkeypatch.setattr(
        rag_service,
        "retrieve_repository_chunks",
        lambda **kwargs: retrieved_chunks,
    )

    monkeypatch.setattr(
        rag_service,
        "get_llm_provider",
        lambda: FakeProvider(),
    )

    result = await rag_service.answer_repository_question(
        repository_id=1,
        query="Where is JWT authentication implemented?",
    )

    assert result["provider"] == "gemini"
    assert result["model"] == "test-model"

    assert "[S1]" in result["answer"]

    assert len(result["sources"]) == 1

    source = result["sources"][0]

    assert source["source_id"] == "S1"
    assert source["file_path"] == "app/core/security.py"
    assert source["start_line"] == 10
    assert source["end_line"] == 25
    assert source["commit_sha"] == "abc123def456"
    assert source["score"] == 0.91


@pytest.mark.asyncio
async def test_no_retrieved_chunks_returns_empty_sources(monkeypatch):

    monkeypatch.setattr(
        rag_service,
        "retrieve_repository_chunks",
        lambda **kwargs: [],
    )

    result = await rag_service.answer_repository_question(
        repository_id=1,
        query="Find authentication",
    )

    assert result["provider"] == "none"
    assert result["model"] == "none"
    assert result["sources"] == []
    assert "could not find relevant code" in result["answer"]


@pytest.mark.asyncio
async def test_invalid_repository_id_raises_error():

    with pytest.raises(ValueError):

        await rag_service.answer_repository_question(
            repository_id=0,
            query="Find authentication",
        )


@pytest.mark.asyncio
async def test_empty_query_raises_error():

    with pytest.raises(ValueError):

        await rag_service.answer_repository_question(
            repository_id=1,
            query=" ",
        )


@pytest.mark.asyncio
async def test_retrieval_arguments_are_forwarded(monkeypatch):

    captured = {}

    def fake_retrieval(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        rag_service,
        "retrieve_repository_chunks",
        fake_retrieval,
    )

    await rag_service.answer_repository_question(
        repository_id=42,
        query="Find database connection",
        limit=3,
        score_threshold=0.7,
    )

    assert captured["repository_id"] == 42
    assert captured["query"] == "Find database connection"
    assert captured["limit"] == 3
    assert captured["score_threshold"] == 0.7

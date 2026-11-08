
import pytest

from app.services.embedding_service import EmbeddingService


def test_prepare_embedding_payload_removes_duplicates():

    service = EmbeddingService(
        api_key="test-key"
    )

    chunks = [
        {
            "file_path": "app/auth.py",
            "symbol_name": "create_token",
            "symbol_kind": "function",
            "start_line": 1,
            "end_line": 10,
            "content": "def create_token(): pass",
        },
        {
            "file_path": "app/auth.py",
            "symbol_name": "create_token",
            "symbol_kind": "function",
            "start_line": 1,
            "end_line": 10,
            "content": "def create_token(): pass",
        },
    ]

    prepared = service.prepare_embedding_payload(chunks)

    assert len(prepared) == 1


def test_empty_chunks_are_skipped():

    service = EmbeddingService(
        api_key="test-key"
    )

    chunks = [
        {
            "file_path": "app/auth.py",
            "content": "",
        },
        {
            "file_path": "app/user.py",
            "content": None,
        },
    ]

    result = service.prepare_embedding_payload(chunks)

    assert result == []


def test_document_embedding_task_type():

    service = EmbeddingService(
        api_key="test-key"
    )

    request = service.build_embedding_request(
        ["JWT authentication implementation"]
    )

    assert request["requests"][0]["taskType"] == (
        "RETRIEVAL_DOCUMENT"
    )


def test_query_text_validation():

    service = EmbeddingService(
        api_key="test-key"
    )

    with pytest.raises(ValueError):

        service.generate_query_embedding("   ")
def test_missing_api_key():

    service = EmbeddingService(api_key="")

    chunks = [
        {
            "file_path": "app/main.py",
            "symbol_name": "main",
            "symbol_kind": "function",
            "start_line": 1,
            "end_line": 5,
            "content": "def main(): pass",
        }
    ]

    with pytest.raises(
        ValueError,
        match="Gemini API key is missing"
    ):
        service.generate_embeddings(chunks)
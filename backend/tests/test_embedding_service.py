
import pytest

import app.services.embedding_service as embedding_module

from app.services.embedding_service import EmbeddingService


class FakeEmbeddingModel:

    def __init__(self):
        self.document_calls = []
        self.query_calls = []

    def embed(self, documents, batch_size=256):

        self.document_calls.append({
            "documents": documents,
            "batch_size": batch_size,
        })

        for _ in documents:
            yield [0.01] * 768

    def query_embed(self, query):

        self.query_calls.append(query)

        yield [0.02] * 768


@pytest.fixture
def fake_model(monkeypatch):

    model = FakeEmbeddingModel()

    monkeypatch.setattr(
        embedding_module,
        "_get_cached_embedding_model",
        lambda model_name, cache_dir, threads: model,
    )

    return model


def get_test_chunk():

    return {
        "repository_chunk_id": 101,
        "file_path": "app/auth.py",
        "symbol_name": "login",
        "symbol_kind": "function",
        "start_line": 1,
        "end_line": 5,
        "content": "def login(): return True",
    }


def test_prepare_embedding_payload_removes_duplicates():

    service = EmbeddingService()

    chunks = [
        get_test_chunk(),
        get_test_chunk(),
    ]

    prepared = service.prepare_embedding_payload(chunks)

    assert len(prepared) == 1
    assert prepared[0]["repository_chunk_id"] == 101
    assert prepared[0]["file_path"] == "app/auth.py"
    assert "content:" in prepared[0]["text"]


def test_empty_chunks_are_skipped(fake_model):

    service = EmbeddingService()

    chunks = [
        {
            "repository_chunk_id": 101,
            "file_path": "app/auth.py",
            "content": "",
        }
    ]

    results = service.generate_embeddings(chunks)

    assert results == []
    assert fake_model.document_calls == []


def test_document_embedding_uses_fastembed(fake_model):

    service = EmbeddingService(
        batch_size=16,
    )

    results = service.generate_embeddings([
        get_test_chunk()
    ])

    assert len(results) == 1

    assert len(results[0]["embedding"]) == 768

    assert fake_model.document_calls

    assert (
        fake_model.document_calls[0]["batch_size"]
        == 16
    )


def test_query_embedding_uses_fastembed(fake_model):

    service = EmbeddingService()

    vector = service.generate_query_embedding(
        "How does login work?"
    )

    assert len(vector) == 768
    assert vector[0] == pytest.approx(0.02)

    assert fake_model.query_calls == [
        "How does login work?"
    ]


def test_query_text_validation(fake_model):

    service = EmbeddingService()

    with pytest.raises(
        ValueError,
        match="Query cannot be empty",
    ):
        service.generate_query_embedding("   ")

    assert fake_model.query_calls == []


def test_embedding_does_not_require_api_key(fake_model):

    service = EmbeddingService(
        api_key="",
    )

    results = service.generate_embeddings([
        get_test_chunk()
    ])

    assert len(results) == 1
    assert len(results[0]["embedding"]) == 768


def test_batch_callback_is_preserved(fake_model):

    service = EmbeddingService(
        batch_size=1,
    )

    callback_calls = []

    chunks = [
        get_test_chunk(),
        {
            **get_test_chunk(),
            "repository_chunk_id": 102,
            "file_path": "app/user.py",
            "symbol_name": "get_user",
        },
    ]

    results = service.generate_embeddings(
        chunks,
        on_batch_complete=lambda batch, index, total: (
            callback_calls.append(
                (len(batch), index, total)
            )
        ),
    )

    assert len(results) == 2

    assert callback_calls == [
        (1, 1, 2),
        (1, 2, 2),
    ]


def test_embedding_rejects_wrong_dimension(fake_model):

    service = EmbeddingService()

    with pytest.raises(
        ValueError,
        match="Invalid embedding dimension",
    ):
        service._validate_vector(
            [0.1, 0.2, 0.3],
            expected_dimension=768,
        )


def test_embedding_rejects_nan():

    with pytest.raises(
        ValueError,
        match="NaN or infinity",
    ):
        EmbeddingService._validate_vector(
            [0.1, float("nan")]
        )


def test_embedding_rejects_infinity():

    with pytest.raises(
        ValueError,
        match="NaN or infinity",
    ):
        EmbeddingService._validate_vector(
            [0.1, float("inf")]
        )


def test_invalid_batch_size():

    with pytest.raises(
        ValueError,
        match="Batch size",
    ):
        EmbeddingService(batch_size=0)

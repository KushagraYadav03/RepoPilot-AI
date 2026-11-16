
import uuid
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient

from app.services.qdrant_service import QdrantVectorStore


class FakeQdrantClient:

    def __init__(self):
        self.upsert_calls = []
        self.query_calls = []
        self.delete_calls = []
        self.created_collections = []

        self.collection_exists_value = False
        self.vectors_config = None

    def collection_exists(self, collection_name):
        return self.collection_exists_value

    def create_collection(
        self,
        collection_name,
        vectors_config,
    ):
        self.created_collections.append(
            {
                "collection_name": collection_name,
                "vectors_config": vectors_config,
            }
        )

        self.vectors_config = vectors_config
        self.collection_exists_value = True

        return True

    def get_collection(self, collection_name):
        if not self.collection_exists_value:
            raise ValueError("Collection does not exist")

        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=self.vectors_config,
                )
            )
        )

    def upsert(
        self,
        collection_name,
        points,
        wait=True,
    ):
        self.upsert_calls.append(
            {
                "collection_name": collection_name,
                "points": points,
                "wait": wait,
            }
        )

        return {"status": "ok"}

    def query_points(
        self,
        collection_name,
        query,
        query_filter,
        limit,
        with_payload,
        score_threshold=None,
        with_vectors=False,
    ):
        self.query_calls.append(
            {
                "collection_name": collection_name,
                "query": query,
                "query_filter": query_filter,
                "limit": limit,
                "with_payload": with_payload,
                "score_threshold": score_threshold,
                "with_vectors": with_vectors,
            }
        )

        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    id="point-1",
                    score=0.91,
                    payload={
                        "repository_id": 7,
                        "repository_chunk_id": 101,
                        "file_path": "app/auth.py",
                        "symbol_name": "login",
                        "symbol_kind": "function",
                    },
                )
            ]
        )

    def delete(
        self,
        collection_name,
        points_selector,
        wait=True,
    ):
        self.delete_calls.append(
            {
                "collection_name": collection_name,
                "points_selector": points_selector,
                "wait": wait,
            }
        )

        return {"status": "ok"}


def get_test_point():
    return {
        "id": 101,
        "repository_chunk_id": 101,
        "repository_id": 7,
        "file_path": "app/auth.py",
        "symbol_name": "login",
        "symbol_kind": "function",
        "start_line": 10,
        "end_line": 20,
        "content": "def login():\n    return 'ok'",
        "vector": [0.1, 0.2, 0.3],
        "commit_sha": "abc123",
    }


def prepare_existing_collection(fake_client):
    fake_client.collection_exists_value = True

    fake_client.vectors_config = SimpleNamespace(
        size=3,
    )


def test_qdrant_service_upserts_repository_metadata_and_vectors():

    fake_client = FakeQdrantClient()

    service = QdrantVectorStore(
        collection_name="repo_chunks_jina",
        client=fake_client,
    )

    results = service.upsert_points(
        [get_test_point()]
    )

    assert len(results) == 1
    assert isinstance(results[0], str)

    assert len(fake_client.created_collections) == 1

    upsert_call = fake_client.upsert_calls[0]

    assert upsert_call["collection_name"] == "repo_chunks_jina"

    point = upsert_call["points"][0]
    payload = point.payload

    assert point.vector == [0.1, 0.2, 0.3]

    assert payload["repository_id"] == 7
    assert payload["repository_chunk_id"] == 101

    assert payload["file_path"] == "app/auth.py"
    assert payload["symbol_name"] == "login"
    assert payload["symbol_kind"] == "function"
    assert payload["start_line"] == 10
    assert payload["end_line"] == 20
    assert payload["commit_sha"] == "abc123"

    assert payload["metadata"]["repository_chunk_id"] == 101


def test_same_chunk_generates_same_point_id():

    fake_client = FakeQdrantClient()

    service = QdrantVectorStore(
        collection_name="repo_chunks_jina",
        client=fake_client,
    )

    first_result = service.upsert_points(
        [get_test_point()]
    )

    second_result = service.upsert_points(
        [get_test_point()]
    )

    assert first_result == second_result

    assert len(fake_client.created_collections) == 1
    assert len(fake_client.upsert_calls) == 2


def test_qdrant_service_searches_only_repository_scoped_points():

    fake_client = FakeQdrantClient()
    prepare_existing_collection(fake_client)

    service = QdrantVectorStore(
        collection_name="repo_chunks_jina",
        client=fake_client,
    )

    results = service.search_repository(
        repository_id=7,
        query_vector=[0.1, 0.2, 0.3],
        limit=5,
    )

    assert len(results) == 1

    query_call = fake_client.query_calls[0]

    assert query_call["collection_name"] == "repo_chunks_jina"
    assert query_call["query"] == [0.1, 0.2, 0.3]
    assert query_call["limit"] == 5
    assert query_call["with_payload"] is True

    repository_condition = (
        query_call["query_filter"].must[0]
    )

    assert repository_condition.key == "repository_id"
    assert repository_condition.match.value == 7


def test_qdrant_service_deletes_repository_file_vectors():

    fake_client = FakeQdrantClient()
    prepare_existing_collection(fake_client)

    service = QdrantVectorStore(
        collection_name="repo_chunks_jina",
        client=fake_client,
    )

    result = service.delete_repository_file(
        repository_id=7,
        file_path="app/auth.py",
    )

    assert result is True
    assert len(fake_client.delete_calls) == 1

    delete_call = fake_client.delete_calls[0]

    assert delete_call["collection_name"] == "repo_chunks_jina"

    conditions = (
        delete_call["points_selector"].filter.must
    )

    assert conditions[0].key == "repository_id"
    assert conditions[0].match.value == 7

    assert conditions[1].key == "file_path"
    assert conditions[1].match.value == "app/auth.py"


def test_qdrant_service_skips_empty_vectors():

    fake_client = FakeQdrantClient()

    service = QdrantVectorStore(
        collection_name="repo_chunks_jina",
        client=fake_client,
    )

    point = get_test_point()
    point["vector"] = []

    results = service.upsert_points([point])

    assert results == []
    assert fake_client.upsert_calls == []
    assert fake_client.created_collections == []


def test_qdrant_service_rejects_different_vector_dimensions():

    fake_client = FakeQdrantClient()

    service = QdrantVectorStore(
        collection_name="repo_chunks_jina",
        client=fake_client,
    )

    first_point = get_test_point()

    second_point = get_test_point()
    second_point["id"] = 102
    second_point["repository_chunk_id"] = 102
    second_point["file_path"] = "app/user.py"
    second_point["vector"] = [0.1, 0.2]

    with pytest.raises(
        ValueError,
        match="same dimension",
    ):
        service.upsert_points(
            [first_point, second_point]
        )


def test_qdrant_service_rejects_missing_repository_chunk_id():

    fake_client = FakeQdrantClient()

    service = QdrantVectorStore(
        collection_name="repo_chunks_jina",
        client=fake_client,
    )

    point = get_test_point()
    point.pop("repository_chunk_id")
    point.pop("id")

    with pytest.raises(
        ValueError,
        match="repository_chunk_id",
    ):
        service.upsert_points([point])


def test_qdrant_service_rejects_duplicate_chunk_ids():

    fake_client = FakeQdrantClient()

    service = QdrantVectorStore(
        collection_name="repo_chunks_jina",
        client=fake_client,
    )

    first_point = get_test_point()

    second_point = get_test_point()
    second_point["file_path"] = "app/user.py"

    with pytest.raises(
        ValueError,
        match="duplicate",
    ):
        service.upsert_points(
            [first_point, second_point]
        )


def test_point_id_is_valid_uuid5():

    point_id = QdrantVectorStore._get_point_id(
        {"repository_chunk_id": 101}
    )

    parsed_uuid = uuid.UUID(point_id)

    assert parsed_uuid.version == 5
    assert str(parsed_uuid) == point_id


def test_point_id_matches_expected_uuid5_mapping():

    expected = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "repopilot-point-id:101",
        )
    )

    actual = QdrantVectorStore._get_point_id(
        {"repository_chunk_id": 101}
    )

    assert actual == expected


def test_different_chunks_generate_different_point_ids():

    first_id = QdrantVectorStore._get_point_id(
        {"repository_chunk_id": 101}
    )

    second_id = QdrantVectorStore._get_point_id(
        {"repository_chunk_id": 102}
    )

    assert first_id != second_id


def test_point_id_is_independent_of_repository_id():

    first_id = QdrantVectorStore._get_point_id(
        {
            "repository_id": 7,
            "repository_chunk_id": 101,
        }
    )

    second_id = QdrantVectorStore._get_point_id(
        {
            "repository_id": 8,
            "repository_chunk_id": 101,
        }
    )

    assert first_id == second_id


@pytest.mark.parametrize(
    "chunk_id",
    [0, -1, True, 1.5, "invalid", None],
)
def test_point_id_rejects_invalid_chunk_ids(chunk_id):

    with pytest.raises(ValueError):
        QdrantVectorStore._get_point_id(
            {"repository_chunk_id": chunk_id}
        )


def test_point_id_rejects_mismatched_postgresql_id():

    with pytest.raises(
        ValueError,
        match="must be identical",
    ):
        QdrantVectorStore._get_point_id(
            {
                "id": 102,
                "repository_chunk_id": 101,
            }
        )


def test_qdrant_payload_chunk_id_persisted_and_read_back():

    client = QdrantClient(":memory:")

    try:
        service = QdrantVectorStore(
            collection_name="repo_chunks_payload_test",
            client=client,
        )

        point = get_test_point()

        point["embedding_model"] = (
            "jinaai/jina-embeddings-v2-base-code"
        )

        point["embedding_dimension"] = 3

        inserted_ids = service.upsert_points([point])

        assert len(inserted_ids) == 1

        stored_points = client.retrieve(
            collection_name="repo_chunks_payload_test",
            ids=inserted_ids,
            with_payload=True,
            with_vectors=True,
        )

        assert len(stored_points) == 1

        stored_point = stored_points[0]
        payload = stored_point.payload

        assert payload["repository_id"] == 7
        assert payload["repository_chunk_id"] == 101
        assert payload["metadata"]["repository_chunk_id"] == 101

        # Verify top-level embedding metadata.
        assert payload["embedding_model"] == (
            "jinaai/jina-embeddings-v2-base-code"
        )

        assert payload["embedding_dimension"] == 3

        # Verify nested embedding metadata.
        assert payload["metadata"]["embedding_model"] == (
            "jinaai/jina-embeddings-v2-base-code"
        )

        assert payload["metadata"]["embedding_dimension"] == 3

        expected_id = QdrantVectorStore._get_point_id(
            {"repository_chunk_id": 101}
        )

        assert str(stored_point.id) == expected_id

        # Qdrant stores the normalized vector.
        assert stored_point.vector == pytest.approx(
            [
                0.26726124,
                0.53452248,
                0.80178373,
            ],
            abs=1e-6,
        )

    finally:
        client.close()

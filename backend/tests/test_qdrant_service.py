
from types import SimpleNamespace

import pytest

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
                {
                    "id": "point-1",
                    "score": 0.91,
                    "payload": {
                        "repository_id": 7,
                        "file_path": "app/auth.py",
                        "symbol_name": "login",
                        "symbol_kind": "function",
                    },
                }
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
    """
    Configure the fake client as if a collection
    with three-dimensional vectors already exists.
    """

    fake_client.collection_exists_value = True

    fake_client.vectors_config = SimpleNamespace(
        size=3,
    )


def test_qdrant_service_upserts_repository_metadata_and_vectors():

    fake_client = FakeQdrantClient()

    service = QdrantVectorStore(
        collection_name="repo_chunks",
        client=fake_client,
    )

    results = service.upsert_points(
        [get_test_point()]
    )

    assert len(results) == 1
    assert isinstance(results[0], str)

    assert len(fake_client.created_collections) == 1

    upsert_call = fake_client.upsert_calls[0]

    assert upsert_call["collection_name"] == "repo_chunks"

    point = upsert_call["points"][0]
    payload = point.payload

    assert point.vector == [0.1, 0.2, 0.3]
    assert payload["repository_id"] == 7
    assert payload["file_path"] == "app/auth.py"
    assert payload["symbol_name"] == "login"
    assert payload["symbol_kind"] == "function"
    assert payload["start_line"] == 10
    assert payload["end_line"] == 20
    assert payload["commit_sha"] == "abc123"


def test_same_chunk_generates_same_point_id():

    fake_client = FakeQdrantClient()

    service = QdrantVectorStore(
        collection_name="repo_chunks",
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
        collection_name="repo_chunks",
        client=fake_client,
    )

    results = service.search_repository(
        repository_id=7,
        query_vector=[0.1, 0.2, 0.3],
        limit=5,
    )

    assert len(results) == 1

    query_call = fake_client.query_calls[0]

    assert query_call["collection_name"] == "repo_chunks"
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
        collection_name="repo_chunks",
        client=fake_client,
    )

    result = service.delete_repository_file(
        repository_id=7,
        file_path="app/auth.py",
    )

    assert result is True
    assert len(fake_client.delete_calls) == 1

    delete_call = fake_client.delete_calls[0]

    assert delete_call["collection_name"] == "repo_chunks"

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
        collection_name="repo_chunks",
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
        collection_name="repo_chunks",
        client=fake_client,
    )

    first_point = get_test_point()

    second_point = get_test_point()
    second_point["file_path"] = "app/user.py"
    second_point["vector"] = [0.1, 0.2]

    with pytest.raises(
        ValueError,
        match="same dimension",
    ):
        service.upsert_points(
            [first_point, second_point]
        )


import hashlib
import logging
import math
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        FilterSelector,
        MatchValue,
        PointStruct,
        VectorParams,
    )
except ImportError as exc:
    raise ImportError(
        "qdrant-client is required. Install it using: "
        "pip install qdrant-client"
    ) from exc


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# QDRANT CLIENT
# ---------------------------------------------------------

@lru_cache(maxsize=4)
def _get_cached_local_client(path: str) -> QdrantClient:
    """
    Create one persistent local Qdrant client per resolved path.
    """

    qdrant_path = Path(path)
    qdrant_path.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Creating local Qdrant client at: %s",
        qdrant_path,
    )

    return QdrantClient(path=str(qdrant_path))


def get_local_qdrant_client(path: str) -> QdrantClient:
    """
    Return the cached client using a normalized absolute path.
    """

    normalized_path = str(
        Path(path).expanduser().resolve()
    )

    return _get_cached_local_client(normalized_path)


def close_local_qdrant_clients() -> None:
    """
    Close cached local Qdrant clients during application shutdown.

    Existing persistent Qdrant data is not deleted.
    """

    cache = _get_cached_local_client

    logger.info(
        "Closing cached Qdrant clients. Cache entries: %s",
        cache.cache_info().currsize,
    )

    normalized_path = str(
        Path(settings.qdrant_path).expanduser().resolve()
    )

    clients = []

    if cache.cache_info().currsize > 0:
        try:
            client = cache(normalized_path)
            clients.append(client)

        except Exception:
            logger.exception(
                "Unable to retrieve cached Qdrant client"
            )

    cache.cache_clear()

    for client in clients:
        try:
            client.close()

            logger.info(
                "Local Qdrant client closed successfully"
            )

        except Exception:
            logger.exception(
                "Failed to close local Qdrant client"
            )


# ---------------------------------------------------------
# QDRANT VECTOR STORE
# ---------------------------------------------------------

class QdrantVectorStore:

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        collection_name: str | None = None,
        client: QdrantClient | None = None,
    ):
        self.path = str(settings.qdrant_path)

        self.collection_name = (
            collection_name
            or settings.qdrant_collection
        )

        if client is not None:
            self.client = client

        elif url:
            self.client = QdrantClient(
                url=url,
                api_key=api_key,
            )

        else:
            self.client = get_local_qdrant_client(
                self.path
            )

    # -----------------------------------------------------
    # COLLECTION HELPERS
    # -----------------------------------------------------

    def _collection_exists(self) -> bool:
        return self.client.collection_exists(
            collection_name=self.collection_name
        )

    def _validate_collection_dimension(
        self,
        vector_size: int,
    ) -> None:

        collection = self.client.get_collection(
            collection_name=self.collection_name
        )

        vectors_config = collection.config.params.vectors

        if isinstance(vectors_config, dict):
            raise ValueError(
                f"Collection '{self.collection_name}' uses "
                "named vectors. This service expects one "
                "unnamed vector per point."
            )

        existing_size = getattr(
            vectors_config,
            "size",
            None,
        )

        if existing_size is None:
            raise ValueError(
                "Unable to determine Qdrant collection "
                "vector dimension."
            )

        if existing_size != vector_size:
            raise ValueError(
                "Qdrant collection and incoming embeddings "
                "must use the same dimension. "
                f"Collection dimension: {existing_size}, "
                f"incoming dimension: {vector_size}. "
                "Do not delete the collection automatically. "
                "Check the embedding model and migration plan."
            )

    def ensure_collection(
        self,
        vector_size: int,
    ) -> None:

        if vector_size <= 0:
            raise ValueError(
                "Vector dimension must be greater than zero."
            )

        if self._collection_exists():
            self._validate_collection_dimension(
                vector_size
            )
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )

        self._validate_collection_dimension(
            vector_size
        )

    # -----------------------------------------------------
    # POINT ID
    # -----------------------------------------------------

    @staticmethod
    def _get_point_id(
        item: dict[str, Any],
    ) -> str:

        supplied_id = item.get("id")

        if isinstance(supplied_id, int) and supplied_id >= 0:
            return str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"repopilot-point-id:{supplied_id}",
                )
            )

        if isinstance(supplied_id, str):
            try:
                return str(uuid.UUID(supplied_id))
            except ValueError:
                pass

        content = (
            item.get("content")
            or item.get("text")
            or ""
        )

        content_hash = hashlib.sha256(
            str(content).encode("utf-8")
        ).hexdigest()

        identity = "|".join(
            [
                str(item.get("repository_id", "")),
                str(item.get("file_path", "")),
                str(item.get("symbol_name", "")),
                str(item.get("symbol_kind", "")),
                str(item.get("start_line", 1)),
                str(item.get("end_line", 1)),
                content_hash,
            ]
        )

        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                identity,
            )
        )

    # -----------------------------------------------------
    # UPSERT
    # -----------------------------------------------------

    def upsert_points(
        self,
        points: Iterable[dict[str, Any]],
    ) -> list[str]:

        prepared_points = list(points or [])

        if not prepared_points:
            return []

        point_structs = []
        point_ids = []
        expected_dimension = None

        for index, item in enumerate(prepared_points):

            if not isinstance(item, dict):
                raise TypeError(
                    f"Point at index {index} must be a dictionary."
                )

            repository_id = item.get("repository_id")
            file_path = item.get("file_path")

            if repository_id is None:
                raise ValueError(
                    f"Missing repository_id at point {index}."
                )

            if not file_path:
                raise ValueError(
                    f"Missing file_path at point {index}."
                )

            vector = item.get("vector")

            if vector is None:
                vector = item.get("embedding")

            if vector is None:
                raise ValueError(
                    f"Missing vector at point {index}."
                )

            if not isinstance(vector, (list, tuple)):
                raise ValueError(
                    f"Invalid vector at point {index}."
                )

            if len(vector) == 0:
                continue

            try:
                vector = [
                    float(value)
                    for value in vector
                ]
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Vector contains a non-numeric value "
                    f"at point {index}."
                ) from exc

            if not all(
                math.isfinite(value)
                for value in vector
            ):
                raise ValueError(
                    f"Vector contains NaN or infinity "
                    f"at point {index}."
                )

            if expected_dimension is None:
                expected_dimension = len(vector)

            elif len(vector) != expected_dimension:
                raise ValueError(
                    "All embedding vectors must have the "
                    "same dimension. "
                    f"Expected {expected_dimension}, "
                    f"received {len(vector)} at point {index}."
                )

            content = item.get("content") or ""

            embedding_text = (
                item.get("embedding_text")
                or item.get("text")
                or content
            )

            metadata = item.get("metadata") or {}

            if not isinstance(metadata, dict):
                raise ValueError(
                    f"Metadata must be a dictionary "
                    f"at point {index}."
                )

            payload = {
                "repository_id": int(repository_id),
                "file_path": str(file_path),
                "symbol_name": (
                    item.get("symbol_name")
                    or metadata.get("symbol_name")
                    or "unknown"
                ),
                "symbol_kind": (
                    item.get("symbol_kind")
                    or metadata.get("symbol_kind")
                    or "unknown"
                ),
                "start_line": int(
                    item.get("start_line")
                    or metadata.get("start_line")
                    or 1
                ),
                "end_line": int(
                    item.get("end_line")
                    or metadata.get("end_line")
                    or 1
                ),
                "content": str(content),
                "embedding_text": str(embedding_text),
                "commit_sha": (
                    item.get("commit_sha")
                    or metadata.get("commit_sha")
                ),
                "metadata": metadata,
            }

            point_id = self._get_point_id(
                {
                    **item,
                    "content": content or embedding_text,
                }
            )

            point_structs.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

            point_ids.append(point_id)

        if not point_structs:
            return []

        self.ensure_collection(
            expected_dimension
        )

        self.client.upsert(
            collection_name=self.collection_name,
            points=point_structs,
            wait=True,
        )

        return point_ids

    # -----------------------------------------------------
    # SEARCH
    # -----------------------------------------------------

    def search_repository(
        self,
        repository_id: int,
        query_vector: list[float],
        limit: int = 5,
        score_threshold: float | None = None,
    ) -> list[Any]:

        if not query_vector:
            raise ValueError(
                "Query vector cannot be empty."
            )

        if limit <= 0:
            raise ValueError(
                "Search limit must be greater than zero."
            )

        try:
            query_vector = [
                float(value)
                for value in query_vector
            ]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Query vector contains a non-numeric value."
            ) from exc

        if not all(
            math.isfinite(value)
            for value in query_vector
        ):
            raise ValueError(
                "Query vector contains NaN or infinity."
            )

        if not self._collection_exists():
            return []

        self._validate_collection_dimension(
            len(query_vector)
        )

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="repository_id",
                        match=MatchValue(
                            value=int(repository_id)
                        ),
                    )
                ]
            ),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )

        return response.points

    # -----------------------------------------------------
    # GET FILE POINT IDS
    # -----------------------------------------------------

    def get_repository_file_point_ids(
        self,
        repository_id: int,
        file_path: str,
    ) -> list[str]:

        if not self._collection_exists():
            return []

        scroll_filter = Filter(
            must=[
                FieldCondition(
                    key="repository_id",
                    match=MatchValue(
                        value=int(repository_id)
                    ),
                ),
                FieldCondition(
                    key="file_path",
                    match=MatchValue(
                        value=file_path
                    ),
                ),
            ]
        )

        point_ids = []
        offset = None

        while True:
            records, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )

            point_ids.extend(
                str(record.id)
                for record in records
            )

            if next_offset is None:
                break

            offset = next_offset

        return point_ids

    # -----------------------------------------------------
    # UPDATE EXISTING FILE COMMIT SHA
    # -----------------------------------------------------

    def update_repository_file_commit_sha(
        self,
        repository_id: int,
        file_path: str,
        commit_sha: str,
    ) -> bool:

        if not commit_sha:
            return False

        if not self._collection_exists():
            return False

        self.client.set_payload(
            collection_name=self.collection_name,
            payload={
                "commit_sha": commit_sha,
            },
            points=Filter(
                must=[
                    FieldCondition(
                        key="repository_id",
                        match=MatchValue(
                            value=int(repository_id),
                        ),
                    ),
                    FieldCondition(
                        key="file_path",
                        match=MatchValue(
                            value=file_path,
                        ),
                    ),
                ]
            ),
            wait=True,
        )

        return True

    # -----------------------------------------------------
    # DELETE FILE VECTORS
    # -----------------------------------------------------

    def delete_repository_file(
        self,
        repository_id: int,
        file_path: str,
    ) -> bool:

        if not self._collection_exists():
            return False

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="repository_id",
                            match=MatchValue(
                                value=int(repository_id)
                            ),
                        ),
                        FieldCondition(
                            key="file_path",
                            match=MatchValue(
                                value=file_path,
                            ),
                        ),
                    ]
                )
            ),
            wait=True,
        )

        return True

    # -----------------------------------------------------
    # DELETE SELECTED POINT IDS
    # -----------------------------------------------------

    def delete_points_by_ids(
        self,
        point_ids: list[str],
    ) -> bool:

        if not point_ids:
            return True

        if not self._collection_exists():
            return False

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=point_ids,
            wait=True,
        )

        return True


# ---------------------------------------------------------
# PUBLIC WRAPPERS
# ---------------------------------------------------------

def store_repository_embeddings(
    points: Iterable[dict[str, Any]],
    repository_id: int,
    **kwargs: Any,
) -> list[str]:

    store = QdrantVectorStore(**kwargs)

    prepared = []

    for point in points:

        metadata = point.get("metadata") or {}

        if not isinstance(metadata, dict):
            raise ValueError(
                "Embedding metadata must be a dictionary."
            )

        content = (
            point.get("content")
            or metadata.get("content")
            or ""
        )

        embedding_text = (
            point.get("text")
            or point.get("embedding_text")
            or content
        )

        vector = point.get("embedding")

        if vector is None:
            vector = point.get("vector")

        prepared.append(
            {
                "id": point.get("id"),
                "repository_id": repository_id,
                "file_path": (
                    point.get("file_path")
                    or metadata.get("file_path")
                ),
                "symbol_name": (
                    point.get("symbol_name")
                    or metadata.get("symbol_name")
                    or "unknown"
                ),
                "symbol_kind": (
                    point.get("symbol_kind")
                    or metadata.get("symbol_kind")
                    or "unknown"
                ),
                "start_line": (
                    point.get("start_line")
                    or metadata.get("start_line")
                    or 1
                ),
                "end_line": (
                    point.get("end_line")
                    or metadata.get("end_line")
                    or 1
                ),
                "commit_sha": (
                    point.get("commit_sha")
                    or metadata.get("commit_sha")
                ),
                "content": content,
                "embedding_text": embedding_text,
                "text": embedding_text,
                "vector": vector,
                "metadata": metadata,
            }
        )

    return store.upsert_points(prepared)


def query_repository_embeddings(
    repository_id: int,
    query_vector: list[float],
    limit: int = 5,
    score_threshold: float | None = None,
    **kwargs: Any,
) -> list[Any]:

    store = QdrantVectorStore(**kwargs)

    return store.search_repository(
        repository_id=repository_id,
        query_vector=query_vector,
        limit=limit,
        score_threshold=score_threshold,
    )


def delete_repository_file_embeddings(
    repository_id: int,
    file_path: str,
    **kwargs: Any,
) -> bool:

    store = QdrantVectorStore(**kwargs)

    return store.delete_repository_file(
        repository_id=repository_id,
        file_path=file_path,
    )


def get_repository_file_point_ids(
    repository_id: int,
    file_path: str,
    **kwargs: Any,
) -> list[str]:

    store = QdrantVectorStore(**kwargs)

    return store.get_repository_file_point_ids(
        repository_id=repository_id,
        file_path=file_path,
    )


def delete_repository_points_by_ids(
    point_ids: list[str],
    **kwargs: Any,
) -> bool:

    store = QdrantVectorStore(**kwargs)

    return store.delete_points_by_ids(point_ids)


# ---------------------------------------------------------
# UPDATE FILE COMMIT SHA PUBLIC WRAPPER
# ---------------------------------------------------------

def update_repository_file_commit_sha(
    repository_id: int,
    file_path: str,
    commit_sha: str,
    **kwargs: Any,
) -> bool:

    store = QdrantVectorStore(**kwargs)

    return store.update_repository_file_commit_sha(
        repository_id=repository_id,
        file_path=file_path,
        commit_sha=commit_sha,
    )

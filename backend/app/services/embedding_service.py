
import hashlib
import logging
import math

from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from app.core.config import settings


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# FASTEMBED MODEL CACHE
# ---------------------------------------------------------

@lru_cache(maxsize=2)
def _get_cached_embedding_model(
    model_name: str,
    cache_dir: str,
    threads: int,
):
    """
    Load FastEmbed model once and reuse it.

    Model download happens automatically on first use.
    """

    from fastembed import TextEmbedding

    Path(cache_dir).mkdir(
        parents=True,
        exist_ok=True,
    )

    logger.info(
        "Loading local embedding model: %s",
        model_name,
    )

    model = TextEmbedding(
        model_name=model_name,
        cache_dir=cache_dir,
        threads=threads,
    )

    logger.info(
        "Local embedding model loaded successfully."
    )

    return model


class EmbeddingService:

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: Optional[int] = None,
        max_retries: int = 8,
        timeout: float = 60.0,
    ):
        """
        Local FastEmbed implementation.

        api_key, max_retries and timeout are retained
        for backward compatibility with older callers.

        They are not used for local inference.
        """

        self.model_name = (
            model
            or getattr(
                settings,
                "embedding_model",
                "jinaai/jina-embeddings-v2-base-code",
            )
        )

        self.batch_size = (
            batch_size
            if batch_size is not None
            else settings.embedding_batch_size
        )

        if self.batch_size <= 0:
            raise ValueError(
                "Batch size must be greater than zero"
            )

        self.embedding_dimension = (
            settings.embedding_dimension
        )

        self.cache_dir = settings.embedding_cache_dir

        self.threads = settings.embedding_threads

        self._model = None

    # -----------------------------------------------------
    # MODEL INITIALIZATION
    # -----------------------------------------------------

    def _get_model(self):

        if self._model is None:

            self._model = _get_cached_embedding_model(
                self.model_name,
                self.cache_dir,
                self.threads,
            )

        return self._model

    # -----------------------------------------------------
    # TEXT NORMALIZATION
    # -----------------------------------------------------

    @staticmethod
    def _normalize_text(value: Any) -> str:

        if value is None:
            return ""

        if not isinstance(value, str):
            value = str(value)

        return value.strip()

    # -----------------------------------------------------
    # CHUNK IDENTITY
    # -----------------------------------------------------

    @staticmethod
    def _get_chunk_identity(
        chunk: dict,
        content: str,
    ) -> tuple:

        return (
            chunk.get("file_path"),
            chunk.get("symbol_name"),
            chunk.get("symbol_kind"),
            chunk.get("start_line"),
            chunk.get("end_line"),
            hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest(),
        )

    # -----------------------------------------------------
    # BUILD ENRICHED CHUNK TEXT
    # -----------------------------------------------------

    def _build_chunk_text(
        self,
        chunk: dict,
    ) -> str:

        content = self._normalize_text(
            chunk.get("content")
        )

        if not content:
            return ""

        parts = []

        metadata_fields = (
            ("file_path", "file_path"),
            ("symbol_name", "symbol_name"),
            ("symbol_kind", "symbol_kind"),
            ("start_line", "start_line"),
            ("end_line", "end_line"),
        )

        for field, label in metadata_fields:

            value = chunk.get(field)

            if value is not None and str(value).strip():

                parts.append(
                    f"{label}: {value}"
                )

        parts.append(
            f"content:\n{content}"
        )

        return "\n".join(parts)

    # -----------------------------------------------------
    # PREPARE EMBEDDING PAYLOAD
    # -----------------------------------------------------

    def prepare_embedding_payload(
        self,
        chunks: Sequence[dict],
    ) -> list[dict]:

        prepared = []

        seen_chunks = set()
        seen_ids = set()

        for chunk in chunks or []:

            if not isinstance(chunk, dict):
                raise TypeError(
                    "Every chunk must be a dictionary"
                )

            content = self._normalize_text(
                chunk.get("content")
            )

            enriched_text = self._build_chunk_text(
                chunk
            )

            if not enriched_text:
                continue

            chunk_identity = self._get_chunk_identity(
                chunk,
                content,
            )

            if chunk_identity in seen_chunks:
                continue

            chunk_id = chunk.get(
                "repository_chunk_id",
                chunk.get("id"),
            )

            if chunk_id is not None:

                if chunk_id in seen_ids:
                    continue

                seen_ids.add(chunk_id)

            seen_chunks.add(chunk_identity)

            prepared.append({
                "repository_chunk_id": chunk_id,
                "file_path": chunk.get("file_path"),
                "symbol_name": chunk.get("symbol_name"),
                "symbol_kind": chunk.get("symbol_kind"),
                "start_line": chunk.get("start_line"),
                "end_line": chunk.get("end_line"),
                "content": content,
                "text": enriched_text,
            })

        return prepared

    # -----------------------------------------------------
    # VECTOR VALIDATION
    # -----------------------------------------------------

    @staticmethod
    def _validate_vector(
        vector: Any,
        expected_dimension: Optional[int] = None,
    ) -> list[float]:

        # FastEmbed commonly returns NumPy arrays.
        if hasattr(vector, "tolist"):
            vector = vector.tolist()

        if not isinstance(vector, (list, tuple)):
            raise ValueError(
                "Embedding vector must be a list"
            )

        if not vector:
            raise ValueError(
                "Embedding vector is empty"
            )

        result = []

        for value in vector:

            if isinstance(value, (str, bytes, bool)):
                raise ValueError(
                    "Embedding contains a non-numeric value"
                )

            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    "Embedding contains a non-numeric value"
                ) from exc

            if not math.isfinite(number):
                raise ValueError(
                    "Embedding contains NaN or infinity"
                )

            result.append(number)

        if (
            expected_dimension is not None
            and len(result) != expected_dimension
        ):

            raise ValueError(
                f"Invalid embedding dimension: expected "
                f"{expected_dimension}, received {len(result)}"
            )

        return result

    # -----------------------------------------------------
    # DOCUMENT EMBEDDING
    # -----------------------------------------------------

    def _generate_batch_embeddings(
        self,
        texts: list[str],
    ) -> list[list[float]]:

        if not texts:
            return []

        model = self._get_model()

        vectors = model.embed(
            texts,
            batch_size=self.batch_size,
        )

        result = []

        for vector in vectors:

            result.append(
                self._validate_vector(
                    vector,
                    expected_dimension=self.embedding_dimension,
                )
            )

        if len(result) != len(texts):

            raise ValueError(
                f"Expected {len(texts)} embeddings, "
                f"received {len(result)}"
            )

        return result

    # -----------------------------------------------------
    # GENERATE DOCUMENT EMBEDDINGS
    # -----------------------------------------------------

    def generate_embeddings(
        self,
        chunks: Sequence[dict],
        on_batch_complete: Optional[
            Callable[[list[dict], int, int], None]
        ] = None,
    ) -> list[dict]:

        prepared = self.prepare_embedding_payload(
            chunks
        )

        if not prepared:
            return []

        total_batches = math.ceil(
            len(prepared) / self.batch_size
        )

        all_results = []

        for batch_index in range(total_batches):

            start = batch_index * self.batch_size

            end = min(
                start + self.batch_size,
                len(prepared),
            )

            batch = prepared[start:end]

            texts = [
                item["text"]
                for item in batch
            ]

            logger.info(
                "Generating local embedding batch %s/%s "
                "(%s chunks)",
                batch_index + 1,
                total_batches,
                len(batch),
            )

            vectors = self._generate_batch_embeddings(
                texts
            )

            if len(vectors) != len(batch):

                raise ValueError(
                    "Embedding count does not match batch size"
                )

            batch_results = []

            for item, vector in zip(batch, vectors):

                result = {
                    **item,
                    "embedding": self._validate_vector(
                        vector,
                        expected_dimension=self.embedding_dimension,
                    ),
                    "embedding_model": self.model_name,
                    "embedding_dimension": self.embedding_dimension,
                }

                batch_results.append(result)

            # Preserve existing ingestion callback.
            if on_batch_complete is not None:

                on_batch_complete(
                    batch_results,
                    batch_index + 1,
                    total_batches,
                )

            all_results.extend(batch_results)

        return all_results

    # -----------------------------------------------------
    # QUERY EMBEDDING
    # -----------------------------------------------------

    def generate_query_embedding(
        self,
        query: str,
    ) -> list[float]:

        normalized_query = self._normalize_text(
            query
        )

        if not normalized_query:

            raise ValueError(
                "Query cannot be empty"
            )

        model = self._get_model()

        vectors = list(
            model.query_embed(
                normalized_query
            )
        )

        if len(vectors) != 1:

            raise ValueError(
                "Invalid query embedding response"
            )

        return self._validate_vector(
            vectors[0],
            expected_dimension=self.embedding_dimension,
        )

    # -----------------------------------------------------
    # CLOSE
    # -----------------------------------------------------

    def close(self):
        """
        No network client exists in local FastEmbed.

        Model instance is cached and reused.
        """
        self._model = None


# ---------------------------------------------------------
# PUBLIC DOCUMENT EMBEDDING WRAPPER
# ---------------------------------------------------------

def embed_repository_chunks(
    chunks: Sequence[dict],
    **kwargs,
) -> list[dict]:

    on_batch_complete = kwargs.pop(
        "on_batch_complete",
        None,
    )

    service = EmbeddingService(**kwargs)

    try:

        return service.generate_embeddings(
            chunks,
            on_batch_complete=on_batch_complete,
        )

    finally:
        service.close()


# ---------------------------------------------------------
# PUBLIC QUERY EMBEDDING WRAPPER
# ---------------------------------------------------------

def embed_query(
    query: str,
    **kwargs,
) -> list[float]:

    service = EmbeddingService(**kwargs)

    try:

        return service.generate_query_embedding(
            query
        )

    finally:
        service.close()

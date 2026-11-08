
import hashlib
import math
from typing import Any, Sequence

import httpx

from app.core.config import settings


class EmbeddingService:

    def __init__(
        self,
        model_name: str | None = None,
        batch_size: int | None = None,
        api_key: str | None = None,
        api_base_url: str = (
            "https://generativelanguage.googleapis.com/v1beta"
        ),
    ):
        self.model_name = (
            model_name
            or getattr(
                settings,
                "embedding_model",
                "gemini-embedding-001",
            )
        ).removeprefix("models/")

        self.batch_size = (
            batch_size
            if batch_size is not None
            else getattr(
                settings,
                "embedding_batch_size",
                16,
            )
        )

        self.api_key = (
            api_key
            if api_key is not None
            else settings.gemini_api_key
        )

        self.api_base_url = api_base_url.rstrip("/")

        if not self.model_name:
            raise ValueError(
                "Embedding model name cannot be empty"
            )

        if self.batch_size <= 0:
            raise ValueError(
                "Batch size must be greater than zero"
            )

    # -----------------------------------------------------
    # TEXT NORMALIZATION
    # -----------------------------------------------------

    def _normalize_text(
        self,
        value: Any,
    ) -> str:

        if value is None:
            return ""

        if isinstance(value, bytes):
            return value.decode(
                "utf-8",
                errors="replace",
            ).strip()

        return str(value).strip()

    # -----------------------------------------------------
    # VECTOR VALIDATION
    # -----------------------------------------------------

    def _validate_embedding(
        self,
        values: Any,
        expected_dimension: int | None = None,
    ) -> list[float]:

        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError(
                "Gemini returned an empty or invalid embedding"
            )

        try:
            vector = [
                float(value)
                for value in values
            ]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Embedding contains a non-numeric value"
            ) from exc

        if not all(
            math.isfinite(value)
            for value in vector
        ):
            raise ValueError(
                "Embedding contains NaN or infinity"
            )

        if (
            expected_dimension is not None
            and len(vector) != expected_dimension
        ):
            raise ValueError(
                "Embedding dimension mismatch. "
                f"Expected {expected_dimension}, "
                f"received {len(vector)}"
            )

        return vector

    # -----------------------------------------------------
    # BUILD ENRICHED TEXT
    # -----------------------------------------------------

    def _build_chunk_text(
        self,
        chunk: dict[str, Any],
    ) -> str | None:

        content = self._normalize_text(
            chunk.get("content")
        )

        if not content:
            return None

        file_path = self._normalize_text(
            chunk.get("file_path")
            or "unknown"
        )

        symbol_name = self._normalize_text(
            chunk.get("symbol_name")
            or "unknown"
        )

        symbol_kind = self._normalize_text(
            chunk.get("symbol_kind")
            or "unknown"
        )

        start_line = chunk.get("start_line")
        end_line = chunk.get("end_line")

        text_parts = [
            f"file_path: {file_path}",
            f"symbol_name: {symbol_name}",
            f"symbol_kind: {symbol_kind}",
        ]

        if start_line is not None and end_line is not None:
            text_parts.append(
                f"line_range: {start_line}-{end_line}"
            )

        text_parts.extend(
            [
                "content:",
                content,
            ]
        )

        return "\n".join(text_parts)

    # -----------------------------------------------------
    # DUPLICATE DETECTION
    # -----------------------------------------------------

    @staticmethod
    def _get_chunk_identity(
        chunk: dict[str, Any],
        content: str,
    ) -> str:
        """
        Build a stable identity for duplicate detection.

        Same content in different files is not considered
        a duplicate.
        """

        identity_parts = [
            str(chunk.get("file_path") or ""),
            str(chunk.get("symbol_name") or ""),
            str(chunk.get("symbol_kind") or ""),
            str(chunk.get("start_line") or ""),
            str(chunk.get("end_line") or ""),
            content,
        ]

        identity = "\x1f".join(identity_parts)

        return hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

    # -----------------------------------------------------
    # PREPARE CHUNKS
    # -----------------------------------------------------

    def prepare_embedding_payload(
        self,
        chunks: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        prepared = []
        seen_chunks = set()

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

            seen_chunks.add(chunk_identity)

            prepared.append(
                {
                    # Original source code.
                    "content": content,

                    # Enriched text sent to Gemini.
                    "text": enriched_text,

                    # Original chunk metadata.
                    "metadata": {
                        "file_path": self._normalize_text(
                            chunk.get("file_path")
                        ),
                        "symbol_name": self._normalize_text(
                            chunk.get("symbol_name")
                        ),
                        "symbol_kind": self._normalize_text(
                            chunk.get("symbol_kind")
                        ),
                        "start_line": chunk.get("start_line"),
                        "end_line": chunk.get("end_line"),
                        "commit_sha": chunk.get("commit_sha"),
                    },
                }
            )

        return prepared

    # -----------------------------------------------------
    # BUILD GEMINI BATCH REQUEST
    # -----------------------------------------------------

    def build_embedding_request(
        self,
        texts: Sequence[str],
    ) -> dict[str, Any]:

        requests = []

        for text in texts:

            value = self._normalize_text(text)

            if not value:
                raise ValueError(
                    "Cannot generate an embedding for empty text"
                )

            requests.append(
                {
                    "model": f"models/{self.model_name}",
                    "content": {
                        "parts": [
                            {
                                "text": value,
                            }
                        ]
                    },
                    "taskType": "RETRIEVAL_DOCUMENT",
                }
            )

        return {
            "requests": requests,
        }

    # -----------------------------------------------------
    # GEMINI API REQUEST
    # -----------------------------------------------------

    def _post_embedding_request(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:

        try:
            response = httpx.post(
                endpoint,
                json=payload,
                timeout=60.0,
            )

            response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                "Gemini embedding API returned HTTP "
                f"{exc.response.status_code}: "
                f"{exc.response.text[:1000]}"
            ) from exc

        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Could not connect to Gemini API: {exc}"
            ) from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise ValueError(
                "Gemini returned an invalid JSON response"
            ) from exc

        if not isinstance(result, dict):
            raise ValueError(
                "Gemini returned an invalid response structure"
            )

        return result

    # -----------------------------------------------------
    # QUERY EMBEDDING
    # -----------------------------------------------------

    def generate_query_embedding(
        self,
        query: str,
    ) -> list[float]:

        query = self._normalize_text(query)

        if not query:
            raise ValueError(
                "Query cannot be empty"
            )

        if not self.api_key:
            raise ValueError(
                "Gemini API key is missing"
            )

        endpoint = (
            f"{self.api_base_url}/models/"
            f"{self.model_name}:embedContent"
            f"?key={self.api_key}"
        )

        request = {
            "model": f"models/{self.model_name}",
            "content": {
                "parts": [
                    {
                        "text": query,
                    }
                ]
            },
            "taskType": "RETRIEVAL_QUERY",
        }

        payload = self._post_embedding_request(
            endpoint,
            request,
        )

        embedding_payload = payload.get(
            "embedding",
            {},
        )

        if not isinstance(embedding_payload, dict):
            raise ValueError(
                "Gemini returned an invalid query embedding"
            )

        values = embedding_payload.get(
            "values",
            [],
        )

        return self._validate_embedding(values)

    # -----------------------------------------------------
    # DOCUMENT EMBEDDINGS
    # -----------------------------------------------------

    def generate_embeddings(
        self,
        chunks: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        prepared = self.prepare_embedding_payload(
            chunks
        )

        if not prepared:
            return []

        if not self.api_key:
            raise ValueError(
                "Gemini API key is missing"
            )

        all_results = []
        expected_dimension = None

        endpoint = (
            f"{self.api_base_url}/models/"
            f"{self.model_name}:batchEmbedContents"
            f"?key={self.api_key}"
        )

        for start in range(
            0,
            len(prepared),
            self.batch_size,
        ):

            batch = prepared[
                start:start + self.batch_size
            ]

            texts = [
                item["text"]
                for item in batch
            ]

            request = self.build_embedding_request(
                texts
            )

            payload = self._post_embedding_request(
                endpoint,
                request,
            )

            batch_embeddings = payload.get(
                "embeddings",
                [],
            )

            if not isinstance(batch_embeddings, list):
                raise ValueError(
                    "Gemini returned an invalid embeddings response"
                )

            if len(batch_embeddings) != len(batch):
                raise ValueError(
                    "Embedding response count does not match "
                    "the number of requested chunks. "
                    f"Requested: {len(batch)}, "
                    f"received: {len(batch_embeddings)}"
                )

            for item, embedding_payload in zip(
                batch,
                batch_embeddings,
            ):

                if not isinstance(embedding_payload, dict):
                    raise ValueError(
                        "Gemini returned an invalid document embedding"
                    )

                values = embedding_payload.get(
                    "values",
                    [],
                )

                vector = self._validate_embedding(
                    values,
                    expected_dimension,
                )

                if expected_dimension is None:
                    expected_dimension = len(vector)

                result = {
                    **item["metadata"],

                    # Original source code.
                    "content": item["content"],

                    # Enriched text used for embedding.
                    "text": item["text"],

                    # Gemini vector.
                    "embedding": vector,
                }

                all_results.append(result)

        return all_results


# ---------------------------------------------------------
# PUBLIC FUNCTIONS
# ---------------------------------------------------------

def embed_repository_chunks(
    chunks,
    **kwargs,
) -> list[dict[str, Any]]:

    service = EmbeddingService(**kwargs)

    return service.generate_embeddings(
        list(chunks)
    )


def embed_query(
    query: str,
    **kwargs,
) -> list[float]:

    service = EmbeddingService(**kwargs)

    return service.generate_query_embedding(
        query
    )

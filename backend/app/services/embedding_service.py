
import hashlib
import logging
import math
import random
import re
import time
from typing import Any, Callable, Optional, Sequence

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class EmbeddingService:

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: Optional[int] = None,
        max_retries: int = 8,
        timeout: float = 60.0,
    ):
        self.api_key = (
            api_key
            if api_key is not None
            else getattr(settings, "gemini_api_key", None)
        )

        configured_model = (
            model
            or getattr(
                settings,
                "embedding_model",
                "gemini-embedding-001",
            )
            or "gemini-embedding-001"
        )

        self.model = configured_model.removeprefix("models/")

        self.batch_size = (
            batch_size
            if batch_size is not None
            else getattr(settings, "embedding_batch_size", 16)
        )

        if self.batch_size <= 0:
            raise ValueError(
                "Batch size must be greater than zero"
            )

        self.max_retries = max(0, max_retries)
        self.timeout = timeout

        self.base_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:batchEmbedContents"
        )

        self.client = httpx.Client(timeout=self.timeout)

    def _ensure_api_key(self):
        if not self.api_key:
            raise ValueError("Gemini API key is missing")

    @staticmethod
    def _normalize_text(value: Any) -> str:

        if value is None:
            return ""

        if not isinstance(value, str):
            value = str(value)

        return value.strip()

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

    def _build_chunk_text(self, chunk: dict) -> str:

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
                parts.append(f"{label}: {value}")

        parts.append(f"content:\n{content}")

        return "\n".join(parts)

    def build_embedding_request(
        self,
        texts: Sequence[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> dict:
        """
        Build Gemini embedding API request payload.
        """

        if task_type not in (
            "RETRIEVAL_DOCUMENT",
            "RETRIEVAL_QUERY",
        ):
            raise ValueError(
                f"Unsupported embedding task type: {task_type}"
            )

        requests = []

        for text in texts:

            normalized_text = self._normalize_text(text)

            if not normalized_text:
                raise ValueError(
                    "Embedding text cannot be empty"
                )

            requests.append({
                "model": f"models/{self.model}",
                "content": {
                    "parts": [
                        {"text": normalized_text}
                    ]
                },
                "taskType": task_type,
            })

        return {
            "requests": requests
        }

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

            enriched_text = self._build_chunk_text(chunk)

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

            if chunk_id is not None and chunk_id in seen_ids:
                continue

            seen_chunks.add(chunk_identity)

            if chunk_id is not None:
                seen_ids.add(chunk_id)

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

    @staticmethod
    def _validate_vector(
        vector: Any,
        expected_dimension: Optional[int] = None,
    ) -> list[float]:

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

            if not isinstance(value, (int, float)):
                raise ValueError(
                    "Embedding contains a non-numeric value"
                )

            number = float(value)

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

    @staticmethod
    def _get_retry_delay(
        response: Optional[httpx.Response],
        attempt: int,
    ) -> float:

        if response is not None:

            retry_after = response.headers.get(
                "Retry-After"
            )

            if retry_after:
                try:
                    return min(float(retry_after), 120.0)
                except ValueError:
                    pass

            response_text = response.text or ""

            match = re.search(
                r"retry in ([0-9.]+)s",
                response_text,
                re.IGNORECASE,
            )

            if match:
                return min(
                    float(match.group(1)),
                    120.0,
                )

        delay = min(2 ** attempt, 60)

        return delay + random.uniform(0, 1)

    def _post_embedding_request(
        self,
        payload: dict,
    ) -> dict:

        self._ensure_api_key()

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        last_error = None

        for attempt in range(self.max_retries + 1):

            response = None

            try:

                response = self.client.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                )

                if response.status_code == 200:
                    return response.json()

                if (
                    response.status_code == 429
                    or response.status_code >= 500
                ):

                    last_error = RuntimeError(
                        f"Gemini HTTP {response.status_code}: "
                        f"{response.text}"
                    )

                    if attempt < self.max_retries:

                        delay = self._get_retry_delay(
                            response,
                            attempt,
                        )

                        logger.warning(
                            "Gemini HTTP %s. Retry %s/%s "
                            "after %.2fs",
                            response.status_code,
                            attempt + 1,
                            self.max_retries,
                            delay,
                        )

                        time.sleep(delay)
                        continue

                response.raise_for_status()

            except (
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as exc:

                last_error = exc

                if attempt >= self.max_retries:
                    break

                delay = self._get_retry_delay(
                    response,
                    attempt,
                )

                logger.warning(
                    "Gemini network error. Retry %s/%s "
                    "after %.2fs: %s",
                    attempt + 1,
                    self.max_retries,
                    delay,
                    exc,
                )

                time.sleep(delay)

        raise RuntimeError(
            f"Gemini embedding request failed after "
            f"{self.max_retries + 1} attempts"
        ) from last_error

    def _generate_batch_embeddings(
        self,
        texts: list[str],
    ) -> list[list[float]]:

        if not texts:
            return []

        payload = self.build_embedding_request(
            texts,
            task_type="RETRIEVAL_DOCUMENT",
        )

        response = self._post_embedding_request(payload)

        embeddings = response.get("embeddings")

        if not isinstance(embeddings, list):
            raise ValueError(
                "Gemini response does not contain embeddings"
            )

        if len(embeddings) != len(texts):
            raise ValueError(
                f"Expected {len(texts)} embeddings, "
                f"received {len(embeddings)}"
            )

        result = []

        for item in embeddings:

            if not isinstance(item, dict):
                raise ValueError(
                    "Invalid embedding response item"
                )

            result.append(
                self._validate_vector(
                    item.get("values")
                )
            )

        return result

    def generate_embeddings(
        self,
        chunks: Sequence[dict],
        on_batch_complete: Optional[
            Callable[[list[dict], int, int], None]
        ] = None,
    ) -> list[dict]:

        prepared = self.prepare_embedding_payload(chunks)

        if not prepared:
            return []

        self._ensure_api_key()

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
                "Generating embedding batch %s/%s (%s chunks)",
                batch_index + 1,
                total_batches,
                len(batch),
            )

            vectors = self._generate_batch_embeddings(texts)

            if len(vectors) != len(batch):
                raise ValueError(
                    "Embedding count does not match batch size"
                )

            batch_results = []

            for item, vector in zip(batch, vectors):

                result = {
                    **item,
                    "embedding": self._validate_vector(vector),
                }

                batch_results.append(result)

            if on_batch_complete is not None:

                on_batch_complete(
                    batch_results,
                    batch_index + 1,
                    total_batches,
                )

            all_results.extend(batch_results)

        return all_results

    def generate_query_embedding(
        self,
        query: str,
    ) -> list[float]:

        normalized_query = self._normalize_text(query)

        if not normalized_query:
            raise ValueError(
                "Query cannot be empty"
            )

        payload = self.build_embedding_request(
            [normalized_query],
            task_type="RETRIEVAL_QUERY",
        )

        response = self._post_embedding_request(payload)

        embeddings = response.get("embeddings")

        if not embeddings or len(embeddings) != 1:
            raise ValueError(
                "Invalid query embedding response"
            )

        if not isinstance(embeddings[0], dict):
            raise ValueError(
                "Invalid query embedding response item"
            )

        return self._validate_vector(
            embeddings[0].get("values")
        )

    def close(self):
        self.client.close()


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


def embed_query(
    query: str,
    **kwargs,
) -> list[float]:

    service = EmbeddingService(**kwargs)

    try:
        return service.generate_query_embedding(query)
    finally:
        service.close()

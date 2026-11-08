from typing import Any

from app.services.embedding_service import embed_query
from app.services.qdrant_service import (
    query_repository_embeddings,
)


def retrieve_repository_chunks(
    repository_id: int,
    query: str,
    limit: int = 5,
    score_threshold: float | None = None,
) -> list[dict[str, Any]]:

    if repository_id <= 0:
        raise ValueError(
            "Repository ID must be greater than zero"
        )

    if not query or not query.strip():
        raise ValueError(
            "Search query cannot be empty"
        )

    if limit <= 0:
        raise ValueError(
            "Limit must be greater than zero"
        )

    query_vector = embed_query(query)

    if not query_vector:
        raise ValueError(
            "Unable to generate query embedding"
        )

    results = query_repository_embeddings(
        repository_id=repository_id,
        query_vector=query_vector,
        limit=limit,
        score_threshold=score_threshold,
    )

    retrieved = []
    seen = set()

    for point in results:

        payload = point.payload or {}

        file_path = payload.get("file_path")
        symbol_name = payload.get("symbol_name")
        start_line = payload.get("start_line")
        end_line = payload.get("end_line")
        content = payload.get("content")

        identity = (
            file_path,
            symbol_name,
            start_line,
            end_line,
        )

        if identity in seen:
            continue

        seen.add(identity)

        retrieved.append(
            {
                "id": str(point.id),
                "repository_id": repository_id,
                "file_path": file_path,
                "symbol_name": symbol_name,
                "symbol_kind": payload.get("symbol_kind"),
                "start_line": start_line,
                "end_line": end_line,
                "content": content,
                "commit_sha": payload.get("commit_sha"),
                "score": point.score,
            }
        )

    return retrieved
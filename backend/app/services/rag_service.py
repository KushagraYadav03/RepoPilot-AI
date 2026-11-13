
from typing import Any

from app.services.llm.factory import get_llm_provider
from app.services.retrieval_service import (
    retrieve_repository_chunks,
)
from app.services.rag_prompt_service import (
    RAG_SYSTEM_INSTRUCTION,
    build_rag_context,
)


async def answer_repository_question(
    repository_id: int,
    query: str,
    limit: int = 5,
    score_threshold: float | None = None,
) -> dict[str, Any]:

    if repository_id <= 0:
        raise ValueError(
            "Repository ID must be greater than zero"
        )

    if not query or not query.strip():
        raise ValueError(
            "Question cannot be empty"
        )

    retrieved_chunks = retrieve_repository_chunks(
        repository_id=repository_id,
        query=query,
        limit=limit,
        score_threshold=score_threshold,
    )

    if not retrieved_chunks:
        return {
            "answer": (
                "I could not find relevant code in this repository "
                "to answer your question."
            ),
            "provider": "none",
            "model": "none",
            "sources": [],
        }

    prompt, sources = build_rag_context(
        query=query,
        retrieved_chunks=retrieved_chunks,
    )

    provider = get_llm_provider()

    response = await provider.generate(
        prompt=prompt,
        system_instruction=RAG_SYSTEM_INSTRUCTION,
        temperature=0.2,
        max_output_tokens=2048,
    )

    response_sources = []

    for source in sources:

        response_sources.append(
            {
                "source_id": source["source_id"],
                "file_path": source["file_path"],
                "symbol_name": source["symbol_name"],
                "symbol_kind": source["symbol_kind"],
                "start_line": source["start_line"],
                "end_line": source["end_line"],
                "commit_sha": source["commit_sha"],
                "score": source["score"],
            }
        )

    return {
        "answer": response.text,
        "provider": response.provider,
        "model": response.model,
        "sources": response_sources,
    }

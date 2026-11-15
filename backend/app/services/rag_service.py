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
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:

    if repository_id <= 0:
        raise ValueError(
            "Repository ID must be greater than zero"
        )

    if not query or not query.strip():
        raise ValueError(
            "Question cannot be empty"
        )

    # Use the last two user questions as extra retrieval context,
    # so follow-ups like "where is its test?" still find the right chunks.

    previous_questions = [
        message["content"]
        for message in (history or [])
        if message.get("role") == "user"
    ][-2:]

    retrieval_query = "\n".join(
        previous_questions + [query]
    )[:2000]

    retrieved_chunks = retrieve_repository_chunks(
        repository_id=repository_id,
        query=retrieval_query,
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

    # Give the LLM the recent conversation so it can resolve
    # references like "it", "that function" or "explain more".

    if history:
        transcript = "\n".join(
            f"{message['role'].upper()}: {message['content'][:500]}"
            for message in history
        )

        prompt = (
            f"Previous conversation:\n{transcript}\n\n{prompt}"
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
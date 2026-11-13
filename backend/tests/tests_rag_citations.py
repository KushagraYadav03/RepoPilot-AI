
import pytest

from app.services.rag_prompt_service import (
    prepare_rag_sources,
    build_rag_context,
)


@pytest.fixture
def chunks():
    return [
        {
            "file_path": "app/core/security.py",
            "symbol_name": "create_access_token",
            "symbol_kind": "function",
            "start_line": 10,
            "end_line": 25,
            "commit_sha": "abc123def456",
            "content": "def create_access_token(data):\n    return token",
            "score": 0.91,
        },
        {
            "file_path": "app/api/routes/auth.py",
            "symbol_name": "login",
            "symbol_kind": "function",
            "start_line": 30,
            "end_line": 48,
            "commit_sha": "def456abc123",
            "content": "def login():\n    authenticate_user()",
            "score": 0.86,
        },
    ]


def test_prepare_sources_generates_source_ids(chunks):

    sources = prepare_rag_sources(chunks)

    assert len(sources) == 2

    assert sources[0]["source_id"] == "S1"
    assert sources[1]["source_id"] == "S2"


def test_prepare_sources_preserves_file_paths(chunks):

    sources = prepare_rag_sources(chunks)

    assert sources[0]["file_path"] == "app/core/security.py"
    assert sources[1]["file_path"] == "app/api/routes/auth.py"


def test_prepare_sources_preserves_line_ranges(chunks):

    sources = prepare_rag_sources(chunks)

    assert sources[0]["start_line"] == 10
    assert sources[0]["end_line"] == 25

    assert sources[1]["start_line"] == 30
    assert sources[1]["end_line"] == 48


def test_prepare_sources_preserves_commit_sha(chunks):

    sources = prepare_rag_sources(chunks)

    assert sources[0]["commit_sha"] == "abc123def456"
    assert sources[1]["commit_sha"] == "def456abc123"


def test_prepare_sources_preserves_similarity_score(chunks):

    sources = prepare_rag_sources(chunks)

    assert sources[0]["score"] == 0.91
    assert sources[1]["score"] == 0.86


def test_empty_content_is_skipped(chunks):

    chunks[0]["content"] = ""

    sources = prepare_rag_sources(chunks)

    assert len(sources) == 1
    assert sources[0]["source_id"] == "S1"
    assert sources[0]["file_path"] == "app/api/routes/auth.py"


def test_build_context_includes_citation_metadata(chunks):

    prompt, sources = build_rag_context(
        query="Where is JWT authentication implemented?",
        retrieved_chunks=chunks,
    )

    assert "[S1]" in prompt or '"source_id": "S1"' in prompt
    assert "app/core/security.py" in prompt
    assert "abc123def456" in prompt
    assert len(sources) == 2


def test_empty_query_raises_error(chunks):

    with pytest.raises(
        ValueError,
        match="Question cannot be empty",
    ):
        build_rag_context(
            query=" ",
            retrieved_chunks=chunks,
        )


def test_empty_sources_raise_error():

    with pytest.raises(
        ValueError,
        match="No valid source code found",
    ):
        build_rag_context(
            query="Explain authentication",
            retrieved_chunks=[],
        )

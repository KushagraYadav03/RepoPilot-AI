
import pytest

from app.services.context_enrichment import (
    build_structural_context_query,
    enrich_review_context,
    extract_changed_imports,
    extract_changed_symbols,
)


def test_extract_python_symbols():

    patch = (
        "@@ -1,2 +1,5 @@\n"
        "+class AuthService:\n"
        "+    def authenticate(self, user):\n"
        "+        return user\n"
    )

    symbols = extract_changed_symbols(patch)

    assert "AuthService" in symbols
    assert "authenticate" in symbols


def test_extract_java_symbols():

    patch = (
        "@@ -1,1 +1,4 @@\n"
        "+public class UserService {\n"
        "+    public String getUser() {\n"
        "+        return \"user\";\n"
    )

    symbols = extract_changed_symbols(patch)

    assert "UserService" in symbols
    assert "getUser" in symbols


def test_extract_javascript_symbols():

    patch = (
        "@@ -1,1 +1,3 @@\n"
        "+class UserService {}\n"
        "+const authenticate = (user) => user;\n"
    )

    symbols = extract_changed_symbols(patch)

    assert "UserService" in symbols
    assert "authenticate" in symbols


def test_extract_imports():

    patch = (
        "@@ -1,1 +1,4 @@\n"
        "+import os\n"
        "+from fastapi import HTTPException\n"
        "+import java.util.List;\n"
        "+import axios from 'axios';\n"
    )

    imports = extract_changed_imports(patch)

    assert len(imports) == 4
    assert "import os" in imports
    assert "from fastapi import HTTPException" in imports


def test_removed_lines_are_not_extracted():

    patch = (
        "@@ -1,2 +1,2 @@\n"
        "-def old_function():\n"
        "+def new_function():\n"
    )

    symbols = extract_changed_symbols(patch)

    assert "new_function" in symbols
    assert "old_function" not in symbols


def test_missing_patch_does_not_fail():

    diff = {
        "files": [
            {
                "filename": "app/auth.py",
                "status": "modified",
                "patch": None,
            }
        ]
    }

    query = build_structural_context_query(diff)

    assert "app/auth.py" in query


def test_build_structural_context_query():

    diff = {
        "files": [
            {
                "filename": "app/auth.py",
                "patch": (
                    "+def authenticate(user):\n"
                    "+import os\n"
                ),
            }
        ]
    }

    query = build_structural_context_query(diff)

    assert "app/auth.py" in query
    assert "authenticate" in query
    assert "import os" in query


def test_enrich_review_context_merges_and_deduplicates():

    diff = {
        "files": [
            {
                "filename": "app/auth.py",
                "patch": "+def authenticate(user):\n",
            }
        ]
    }

    semantic_chunk = {
        "id": "1",
        "file_path": "app/auth.py",
        "symbol_name": "authenticate",
        "start_line": 1,
        "end_line": 10,
        "content": "def authenticate(user): ...",
        "score": 0.85,
    }

    structural_chunk = {
        **semantic_chunk,
        "id": "2",
        "score": 0.95,
    }

    related_chunk = {
        "id": "3",
        "file_path": "app/security.py",
        "symbol_name": "verify_token",
        "start_line": 1,
        "end_line": 15,
        "content": "def verify_token(): ...",
        "score": 0.90,
    }

    def fake_retrieval(**kwargs):

        if "Changed files" in kwargs["query"]:
            return [
                structural_chunk,
                related_chunk,
            ]

        return [semantic_chunk]

    result = enrich_review_context(
        repository_id=1,
        diff=diff,
        base_query="Understand authentication",
        retrieve_chunks=fake_retrieval,
    )

    assert len(result) == 2

    assert result[0]["file_path"] == "app/auth.py"

    assert result[0]["score"] == 0.95

    assert set(result[0]["context_sources"]) == {
        "semantic",
        "structural",
    }


def test_enrich_review_context_uses_two_retrievals():

    diff = {
        "files": [
            {
                "filename": "app/auth.py",
                "patch": None,
            }
        ]
    }

    calls = []

    def fake_retrieval(**kwargs):
        calls.append(kwargs)
        return []

    enrich_review_context(
        repository_id=1,
        diff=diff,
        base_query="Authentication review",
        retrieve_chunks=fake_retrieval,
    )

    assert len(calls) == 2

    assert calls[0]["limit"] == 10
    assert calls[1]["limit"] == 20

    assert calls[0]["repository_id"] == 1
    assert calls[1]["repository_id"] == 1


def test_invalid_repository_id():

    with pytest.raises(ValueError):

        enrich_review_context(
            repository_id=0,
            diff={"files": []},
            base_query="Authentication",
            retrieve_chunks=lambda **kwargs: [],
        )


def test_invalid_retrieval_limit():

    with pytest.raises(ValueError):

        enrich_review_context(
            repository_id=1,
            diff={"files": []},
            base_query="Authentication",
            retrieve_chunks=lambda **kwargs: [],
            semantic_limit=0,
        )

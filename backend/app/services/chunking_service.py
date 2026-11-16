
import ast
from pathlib import PurePosixPath


def _normalize_text(text):
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return text or ""


def _build_chunk(
    file_path,
    symbol_name,
    symbol_kind,
    start_line,
    end_line,
    content,
    commit_sha=None,
):
    return {
        "file_path": file_path,
        "symbol_name": symbol_name,
        "symbol_kind": symbol_kind,
        "start_line": start_line,
        "end_line": end_line,
        "line_count": max(end_line - start_line + 1, 0),
        "content": content,
        "commit_sha": commit_sha,
    }


def _chunk_python_code(file_path, text, commit_sha=None):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _chunk_by_lines(file_path, text, commit_sha)

    lines = text.splitlines()
    chunks = []

    # Collect class, function and async function definitions.
    for node in ast.walk(tree):
        if not isinstance(
            node,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue

        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line)

        content = "\n".join(lines[start_line - 1:end_line])

        symbol_kind = (
            "class"
            if isinstance(node, ast.ClassDef)
            else "function"
        )

        chunks.append(
            _build_chunk(
                file_path=file_path,
                symbol_name=node.name,
                symbol_kind=symbol_kind,
                start_line=start_line,
                end_line=end_line,
                content=content,
                commit_sha=commit_sha,
            )
        )

    # Preserve module-level code such as imports,
    # constants, global variables and executable statements.
    module_nodes = [
        node
        for node in tree.body
        if not isinstance(
            node,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        )
    ]

    if module_nodes:
        start_line = min(node.lineno for node in module_nodes)
        end_line = max(
            getattr(node, "end_lineno", node.lineno)
            for node in module_nodes
        )

        content = "\n".join(lines[start_line - 1:end_line])

        if content.strip():
            chunks.append(
                _build_chunk(
                    file_path=file_path,
                    symbol_name="__module__",
                    symbol_kind="module",
                    start_line=start_line,
                    end_line=end_line,
                    content=content,
                    commit_sha=commit_sha,
                )
            )

    # Files with no definitions or module-level chunks
    # still get line-based chunks.
    if not chunks:
        return _chunk_by_lines(file_path, text, commit_sha)

    return sorted(
        chunks,
        key=lambda chunk: (
            chunk["start_line"],
            chunk["end_line"],
            chunk["symbol_kind"],
        ),
    )


def _chunk_by_lines(
    file_path,
    text,
    commit_sha=None,
    max_lines=80,
    overlap=10,
):
    lines = text.splitlines()

    if not lines:
        return []

    chunks = []
    start = 0

    while start < len(lines):
        end = min(start + max_lines, len(lines))
        content = "\n".join(lines[start:end])

        if content.strip():
            chunks.append(
                _build_chunk(
                    file_path=file_path,
                    symbol_name=PurePosixPath(file_path).stem,
                    symbol_kind="file_section",
                    start_line=start + 1,
                    end_line=end,
                    content=content,
                    commit_sha=commit_sha,
                )
            )

        if end == len(lines):
            break

        start = end - overlap

    return chunks


def chunk_code(
    file_path: str,
    text: str | bytes,
    commit_sha: str | None = None,
):
    code_text = _normalize_text(text)

    if not code_text.strip():
        return []

    suffix = PurePosixPath(file_path).suffix.lower()

    if suffix == ".py":
        return _chunk_python_code(
            file_path,
            code_text,
            commit_sha,
        )

    return _chunk_by_lines(
        file_path,
        code_text,
        commit_sha,
    )

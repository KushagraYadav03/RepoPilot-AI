
import ast
import logging
import re
from collections import defaultdict
from typing import Any, Callable

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.repository_file import RepositoryFile


logger = logging.getLogger(__name__)


# =========================================================
# SYMBOL AND IMPORT EXTRACTION
# =========================================================

PYTHON_SYMBOL_PATTERN = re.compile(
    r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)"
)

GENERAL_SYMBOL_PATTERNS = [
    # Java classes, interfaces, enums and records
    re.compile(
        r"\b(?:class|interface|enum|record)\s+([A-Za-z_]\w*)"
    ),

    # JavaScript named functions
    re.compile(
        r"\bfunction\s+([A-Za-z_]\w*)"
    ),

    # JavaScript arrow functions
    re.compile(
        r"\b(?:const|let|var)\s+([A-Za-z_]\w*)"
        r"\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>"
    ),

    # Java methods
    re.compile(
        r"^\s*"
        r"(?:(?:public|private|protected|static|final|"
        r"abstract|synchronized|native|default)\s+)*"
        r"[\w<>\[\],.?]+\s+"
        r"([A-Za-z_]\w*)\s*\("
    ),
]

IMPORT_PATTERNS = [
    # Python imports
    re.compile(
        r"^\s*(?:from\s+[\w.]+\s+import|import\s+[\w.,* ]+)"
    ),

    # Java imports
    re.compile(
        r"^\s*import\s+(?:static\s+)?[\w.*]+\s*;"
    ),

    # JavaScript imports
    re.compile(
        r"^\s*import\s+.+\s+from\s+['\"].+['\"]"
    ),

    # CommonJS require
    re.compile(
        r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"
    ),
]


# =========================================================
# DIFF ANALYSIS
# =========================================================

def _get_added_lines(patch: str) -> list[str]:

    if not isinstance(patch, str):
        return []

    added_lines = []

    for line in patch.splitlines():

        if line.startswith(("+++", "@@", "---")):
            continue

        if line.startswith("+"):
            added_lines.append(line[1:])

    return added_lines


def extract_changed_symbols(
    patch: str,
) -> list[str]:

    symbols = []

    for line in _get_added_lines(patch):

        match = PYTHON_SYMBOL_PATTERN.match(line)

        if match:
            symbols.append(match.group(1))
            continue

        for pattern in GENERAL_SYMBOL_PATTERNS:

            match = pattern.search(line)

            if match:
                symbols.append(match.group(1))
                break

    return list(dict.fromkeys(symbols))


def extract_changed_imports(
    patch: str,
) -> list[str]:

    imports = []

    for line in _get_added_lines(patch):

        for pattern in IMPORT_PATTERNS:

            if pattern.search(line):
                imports.append(line.strip())
                break

    return list(dict.fromkeys(imports))


# =========================================================
# STRUCTURAL CONTEXT QUERY
# =========================================================

def build_structural_context_query(
    diff: dict[str, Any],
) -> str:

    files = diff.get("files", [])

    if not isinstance(files, list):
        return ""

    file_paths = []
    symbols = []
    imports = []

    for file in files:

        if not isinstance(file, dict):
            continue

        filename = file.get("filename")

        if isinstance(filename, str) and filename.strip():
            file_paths.append(filename.strip())

        patch = file.get("patch") or ""

        if not isinstance(patch, str):
            continue

        symbols.extend(
            extract_changed_symbols(patch)
        )

        imports.extend(
            extract_changed_imports(patch)
        )

    query_parts = [
        "Find existing repository code related to these changes."
    ]

    if file_paths:
        query_parts.append(
            "Changed files: "
            + ", ".join(dict.fromkeys(file_paths))
        )

    if symbols:
        query_parts.append(
            "Changed functions and classes: "
            + ", ".join(dict.fromkeys(symbols))
        )

    if imports:
        query_parts.append(
            "Changed imports and dependencies: "
            + ", ".join(dict.fromkeys(imports))
        )

    return "\n".join(query_parts)[:12000]


# =========================================================
# CHUNK DEDUPLICATION
# =========================================================

def _chunk_identity(
    chunk: dict[str, Any],
) -> tuple:

    return (
        chunk.get("file_path"),
        chunk.get("symbol_name"),
        chunk.get("start_line"),
        chunk.get("end_line"),
        (chunk.get("content") or "").strip(),
    )


def _chunk_score(
    chunk: dict[str, Any],
) -> float:

    try:
        return float(chunk.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# =========================================================
# PYTHON AST HELPERS
# =========================================================

def _get_call_name(
    node: ast.AST,
) -> str | None:

    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        return node.attr

    return None


def _get_node_content(
    source_lines: list[str],
    node: ast.AST,
) -> str:

    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)

    if start is None or end is None:
        return ""

    return "\n".join(
        source_lines[start - 1:end]
    )


def _extract_function_records(
    file_path: str,
    content: str,
) -> tuple[list[dict], list[dict]]:

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return [], []

    source_lines = content.splitlines()

    functions = []
    classes = []

    class_stack = []

    class FunctionVisitor(ast.NodeVisitor):

        def __init__(self):
            self.calls = set()

        def visit_Call(self, node):

            name = _get_call_name(node.func)

            if name:
                self.calls.add(name)

            self.generic_visit(node)

    def visit(node):

        if isinstance(node, ast.ClassDef):

            classes.append({
                "file_path": file_path,
                "symbol_name": node.name,
                "symbol_kind": "class",
                "start_line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
                "content": _get_node_content(
                    source_lines,
                    node,
                ),
            })

            class_stack.append(node.name)

            for child in node.body:
                visit(child)

            class_stack.pop()
            return

        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):

            visitor = FunctionVisitor()
            visitor.visit(node)

            functions.append({
                "file_path": file_path,
                "symbol_name": node.name,
                "symbol_kind": (
                    "async_function"
                    if isinstance(node, ast.AsyncFunctionDef)
                    else "function"
                ),
                "start_line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
                "content": _get_node_content(
                    source_lines,
                    node,
                ),
                "calls": visitor.calls,
                "class_name": (
                    class_stack[-1]
                    if class_stack
                    else None
                ),
            })

            return

        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)

    return functions, classes


# =========================================================
# REPOSITORY SOURCE RETRIEVAL
# =========================================================

def _load_repository_sources(
    repository_id: int,
) -> list[dict[str, Any]]:

    with SessionLocal() as db:

        records = db.scalars(
            select(RepositoryFile).where(
                RepositoryFile.repository_id == repository_id
            )
        ).all()

        return [
            {
                "file_path": record.file_path,
                "content": record.content,
                "commit_sha": None,
            }
            for record in records
            if record.content
        ]


# =========================================================
# STRUCTURAL RELATIONSHIP RETRIEVAL
# =========================================================

def retrieve_structural_relationships(
    repository_id: int,
    diff: dict[str, Any],
) -> list[dict[str, Any]]:

    changed_files = set()
    changed_symbols = set()

    for file in diff.get("files", []):

        if not isinstance(file, dict):
            continue

        filename = file.get("filename")

        if isinstance(filename, str):
            changed_files.add(filename.strip())

        patch = file.get("patch") or ""

        if isinstance(patch, str):
            changed_symbols.update(
                extract_changed_symbols(patch)
            )

    if not changed_symbols:
        return []

    try:
        repository_sources = _load_repository_sources(
            repository_id
        )
    except Exception:
        logger.exception(
            "Unable to load repository source files"
        )
        return []

    all_functions = []
    all_classes = []

    for source in repository_sources:

        functions, classes = _extract_function_records(
            source["file_path"],
            source["content"],
        )

        for item in functions + classes:
            item["commit_sha"] = source.get("commit_sha")

        all_functions.extend(functions)
        all_classes.extend(classes)

    functions_by_name = defaultdict(list)

    for function in all_functions:
        functions_by_name[
            function["symbol_name"]
        ].append(function)

    classes_by_name = defaultdict(list)

    for cls in all_classes:
        classes_by_name[
            cls["symbol_name"]
        ].append(cls)

    results = []
    seen = set()

    def add_result(
        item: dict[str, Any],
        relation: str,
        related_symbol: str,
    ):

        identity = (
            item["file_path"],
            item["symbol_name"],
            item["start_line"],
            item["end_line"],
            relation,
        )

        if identity in seen:
            return

        seen.add(identity)

        results.append({
            **item,
            "score": 0.0,
            "context_sources": ["structural"],
            "context_relation": relation,
            "related_symbol": related_symbol,
        })

    # -----------------------------------------------------
    # CHANGED FUNCTION IMPLEMENTATIONS
    # -----------------------------------------------------

    changed_function_records = []

    for symbol in changed_symbols:

        for function in functions_by_name.get(symbol, []):

            if function["file_path"] in changed_files:

                changed_function_records.append(function)

                add_result(
                    function,
                    "changed_function",
                    symbol,
                )

    # -----------------------------------------------------
    # CALLEES
    # -----------------------------------------------------

    called_names = set()

    for function in changed_function_records:
        called_names.update(function["calls"])

    for called_name in called_names:

        for dependency in functions_by_name.get(
            called_name,
            [],
        ):

            add_result(
                dependency,
                "callee",
                called_name,
            )

    # -----------------------------------------------------
    # CALLERS
    # -----------------------------------------------------

    for function in all_functions:

        matched_calls = (
            function["calls"] & changed_symbols
        )

        for called_name in matched_calls:

            add_result(
                function,
                "caller",
                called_name,
            )

    # -----------------------------------------------------
    # CLASS DEPENDENCIES
    # -----------------------------------------------------

    for function in changed_function_records:

        for dependency in all_classes:

            class_name = dependency["symbol_name"]

            if class_name in function["calls"]:

                add_result(
                    dependency,
                    "class_dependency",
                    class_name,
                )

    # -----------------------------------------------------
    # CHANGED CLASSES
    # -----------------------------------------------------

    for symbol in changed_symbols:

        for dependency in classes_by_name.get(symbol, []):

            if dependency["file_path"] in changed_files:

                add_result(
                    dependency,
                    "changed_class",
                    symbol,
                )

    logger.info(
        "Structural relationships retrieved for repository %s: %s",
        repository_id,
        len(results),
    )

    return results


# =========================================================
# CONTEXT ENRICHMENT
# =========================================================

def enrich_review_context(
    repository_id: int,
    diff: dict[str, Any],
    base_query: str,
    retrieve_chunks: Callable[..., list[dict[str, Any]]],
    semantic_limit: int = 10,
    structural_limit: int = 20,
) -> list[dict[str, Any]]:

    if (
        isinstance(repository_id, bool)
        or not isinstance(repository_id, int)
        or repository_id <= 0
    ):
        raise ValueError(
            "Repository ID must be greater than zero"
        )

    if not isinstance(diff, dict):
        raise ValueError("Invalid diff data")

    if not callable(retrieve_chunks):
        raise ValueError(
            "Chunk retrieval function must be callable"
        )

    if (
        not isinstance(base_query, str)
        or not base_query.strip()
    ):
        raise ValueError(
            "Base retrieval query cannot be empty"
        )

    if (
        semantic_limit <= 0
        or structural_limit <= 0
    ):
        raise ValueError(
            "Retrieval limits must be greater than zero"
        )

    # -----------------------------------------------------
    # STEP 1: SEMANTIC RETRIEVAL
    # -----------------------------------------------------

    semantic_chunks = retrieve_chunks(
        repository_id=repository_id,
        query=base_query,
        limit=semantic_limit,
    )

    if not isinstance(semantic_chunks, list):
        raise ValueError(
            "Semantic retrieval must return a list"
        )

    # -----------------------------------------------------
    # STEP 2: VECTOR STRUCTURAL RETRIEVAL
    # -----------------------------------------------------

    structural_query = build_structural_context_query(
        diff
    )

    structural_chunks = []

    if structural_query:

        structural_chunks = retrieve_chunks(
            repository_id=repository_id,
            query=structural_query,
            limit=structural_limit,
        )

        if not isinstance(structural_chunks, list):
            raise ValueError(
                "Structural retrieval must return a list"
            )

    # -----------------------------------------------------
    # STEP 3: AST STRUCTURAL RELATIONSHIPS
    # -----------------------------------------------------

    relationship_chunks = retrieve_structural_relationships(
        repository_id=repository_id,
        diff=diff,
    )

    # -----------------------------------------------------
    # STEP 4: CHANGED FILES AND SYMBOLS
    # -----------------------------------------------------

    changed_files = set()
    changed_symbols = set()

    for file in diff.get("files", []):

        if not isinstance(file, dict):
            continue

        filename = file.get("filename")

        if isinstance(filename, str):
            changed_files.add(filename.strip())

        patch = file.get("patch") or ""

        if isinstance(patch, str):
            changed_symbols.update(
                extract_changed_symbols(patch)
            )

    # -----------------------------------------------------
    # STEP 5: MERGE AND DEDUPLICATE
    # -----------------------------------------------------

    merged = {}

    sources = (
        ("semantic", semantic_chunks),
        ("structural", structural_chunks),
        ("structural", relationship_chunks),
    )

    for source, chunks in sources:

        for chunk in chunks:

            if not isinstance(chunk, dict):
                continue

            identity = _chunk_identity(chunk)

            existing = merged.get(identity)

            if existing is None:

                merged[identity] = {
                    **chunk,
                    "context_sources": list(
                        chunk.get("context_sources") or [source]
                    ),
                }

            else:

                if source not in existing["context_sources"]:
                    existing["context_sources"].append(source)

                for context_source in (
                    chunk.get("context_sources") or []
                ):

                    if (
                        context_source
                        not in existing["context_sources"]
                    ):
                        existing["context_sources"].append(
                            context_source
                        )

                if _chunk_score(chunk) > _chunk_score(existing):
                    existing["score"] = chunk.get("score")

                if chunk.get("context_relation"):
                    existing["context_relation"] = (
                        chunk["context_relation"]
                    )

                    existing["related_symbol"] = (
                        chunk.get("related_symbol")
                    )

    # -----------------------------------------------------
    # STEP 6: RELEVANCE RANKING
    # -----------------------------------------------------

    relation_priority = {
        "changed_function": 6,
        "changed_class": 6,
        "caller": 5,
        "callee": 5,
        "class_dependency": 4,
    }

    enriched = list(merged.values())

    def ranking_key(chunk):

        relation = relation_priority.get(
            chunk.get("context_relation"),
            0,
        )

        same_file = (
            chunk.get("file_path") in changed_files
        )

        same_symbol = (
            chunk.get("symbol_name") in changed_symbols
        )

        return (
            relation,
            int(same_file),
            int(same_symbol),
            _chunk_score(chunk),
        )

    enriched.sort(
        key=ranking_key,
        reverse=True,
    )

    logger.info(
        "Context enrichment completed for repository %s: "
        "%s semantic chunks, %s structural chunks, "
        "%s relationship chunks, %s unique chunks",
        repository_id,
        len(semantic_chunks),
        len(structural_chunks),
        len(relationship_chunks),
        len(enriched),
    )

    return enriched

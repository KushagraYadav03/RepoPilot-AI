import ast
import re
from pathlib import PurePosixPath

try:
    from tree_sitter import Language, Parser
    from tree_sitter_java import language as java_grammar
    from tree_sitter_python import language as python_grammar
except ImportError:  # pragma: no cover
    Language = None
    Parser = None
    java_grammar = None
    python_grammar = None


def _language_from_grammar(grammar):
    if Language is None or grammar is None:
        return None
    return Language(grammar())


def _node_text(node):
    if node is None:
        return ""
    try:
        return node.text.decode("utf-8")
    except Exception:
        return ""


def _unique_preserve_order(values):
    seen = set()
    ordered = []
    for value in values:
        if not value:
            continue
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _collect_from_tree(tree, kind_map, import_matchers=()):
    classes = []
    functions = []
    imports = []

    def visit(node):
        node_type = getattr(node, "type", "")

        if node_type in kind_map["class"]:
            identifier = next(
                (child for child in node.children if getattr(child, "type", "") == "identifier"),
                None,
            )
            if identifier is not None:
                classes.append(_node_text(identifier))
        elif node_type in kind_map["function"]:
            identifier = next(
                (child for child in node.children if getattr(child, "type", "") == "identifier"),
                None,
            )
            if identifier is not None:
                functions.append(_node_text(identifier))
        elif node_type in kind_map["import"]:
            value = _node_text(node).strip()
            for matcher in import_matchers:
                normalized = matcher(value)
                if normalized:
                    imports.append(normalized)
                    break
            else:
                imports.append(value)

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return classes, functions, imports


def parse_python_symbols(text: str):
    if Parser is not None and python_grammar is not None:
        parser = Parser()
        parser.language = _language_from_grammar(python_grammar)
        try:
            tree = parser.parse(text.encode("utf-8"))
            classes, functions, imports = _collect_from_tree(
                tree,
                {
                    "class": {"class_definition"},
                    "function": {"function_definition", "async_function_definition"},
                    "import": {"import_statement", "import_from_statement"},
                },
                import_matchers=(
                    lambda value: value.replace("import ", "").replace("from ", "").strip().rstrip(";"),
                ),
            )
            classes = _unique_preserve_order(classes)
            functions = _unique_preserve_order(functions)
            imports = _unique_preserve_order(imports)
            return {
                "language": "python",
                "classes": classes,
                "functions": functions,
                "imports": imports,
                "symbol_count": len(classes) + len(functions),
            }
        except Exception:
            pass

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {
            "language": "python",
            "classes": [],
            "functions": [],
            "imports": [],
            "symbol_count": 0,
        }

    classes = []
    functions = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            for alias in node.names:
                imports.append(f"{base}.{alias.name}" if base else alias.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)

    return {
        "language": "python",
        "classes": _unique_preserve_order(classes),
        "functions": _unique_preserve_order(functions),
        "imports": _unique_preserve_order(imports),
        "symbol_count": len(_unique_preserve_order(classes)) + len(_unique_preserve_order(functions)),
    }


def parse_java_symbols(text: str):
    if Parser is not None and java_grammar is not None:
        parser = Parser()
        parser.language = _language_from_grammar(java_grammar)
        try:
            tree = parser.parse(text.encode("utf-8"))
            classes, functions, imports = _collect_from_tree(
                tree,
                {
                    "class": {"class_declaration", "interface_declaration", "enum_declaration"},
                    "function": {"method_declaration"},
                    "import": {"import_declaration"},
                },
                import_matchers=(
                    lambda value: value.replace("import ", "").replace(";", "").strip(),
                ),
            )
            classes = _unique_preserve_order(classes)
            functions = _unique_preserve_order(functions)
            imports = _unique_preserve_order(imports)
            return {
                "language": "java",
                "classes": classes,
                "functions": functions,
                "imports": imports,
                "symbol_count": len(classes) + len(functions),
            }
        except Exception:
            pass

    imports = []
    classes = []
    functions = []

    import_pattern = re.compile(r"^\s*import\s+([A-Za-z0-9_$.]+)\s*;", re.MULTILINE)
    class_pattern = re.compile(
        r"(?:public|protected|private)?\s*(?:abstract\s+|final\s+)?(?:class|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
        re.MULTILINE,
    )
    method_pattern = re.compile(
        r"(?:public|protected|private|static|final|synchronized|abstract|native|strictfp|\s)+[A-Za-z0-9_<>,\[\]\?\s]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*(?:\{|throws)",
        re.MULTILINE,
    )

    imports.extend(import_pattern.findall(text))
    classes.extend(class_pattern.findall(text))
    functions.extend(method_pattern.findall(text))

    classes = _unique_preserve_order(classes)
    functions = _unique_preserve_order(functions)
    imports = _unique_preserve_order(imports)

    return {
        "language": "java",
        "classes": classes,
        "functions": functions,
        "imports": imports,
        "symbol_count": len(classes) + len(functions),
    }


def parse_code_symbols(file_path: str, text: str):
    suffix = PurePosixPath(file_path).suffix.lower()

    if suffix == ".py":
        return parse_python_symbols(text)
    if suffix == ".java":
        return parse_java_symbols(text)

    return {
        "language": suffix.lstrip(".") or "text",
        "classes": [],
        "functions": [],
        "imports": [],
        "symbol_count": 0,
    }

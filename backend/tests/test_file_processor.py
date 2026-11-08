from app.services.chunking_service import chunk_code
from app.services.file_processor import process_file


def test_chunk_python_code_with_metadata():
    content = b"""class UserService:\n    def greet(self, name):\n        return f'Hello {name}'\n\n\ndef helper():\n    return 'done'\n"""

    chunks = chunk_code("app/user_service.py", content.decode("utf-8"), commit_sha="abc123")

    assert len(chunks) == 3
    assert chunks[0]["file_path"] == "app/user_service.py"
    assert chunks[0]["symbol_name"] == "UserService"
    assert chunks[0]["symbol_kind"] == "class"
    assert chunks[0]["commit_sha"] == "abc123"
    assert chunks[0]["start_line"] == 1
    assert chunks[0]["end_line"] == 3
    assert chunks[1]["symbol_name"] == "greet"
    assert chunks[1]["symbol_kind"] == "function"
    assert chunks[2]["symbol_name"] == "helper"
    assert chunks[2]["symbol_kind"] == "function"


def test_process_python_file():
    content = b"print('Hello World')\r\n"

    result = process_file("app/main.py", content)

    assert result is not None
    assert result["file_name"] == "main.py"
    assert result["line_count"] == 1
    assert "\r\n" not in result["content"]


def test_exclude_env_file():
    content = b"SECRET_KEY=12345"

    result = process_file(".env", content)

    assert result is None


def test_exclude_binary_file():
    content = b"\x89PNG\r\n\x1a\n"

    result = process_file("image.png", content)

    assert result is None


def test_exclude_generated_directory():
    content = b"print('hello')"

    result = process_file("__pycache__/main.pyc", content)

    assert result is None


def test_exclude_secret_in_python_file():
    content = b'OPENAI_API_KEY = "sk-proj-1234567890abcdef"\nprint("hello")\n'

    result = process_file("app/main.py", content)

    assert result is None


def test_parse_python_symbols():
    content = b"import os\n\nclass UserService:\n    def greet(self, name):\n        return f'Hello {name}'\n\n\ndef helper():\n    return 'done'\n"

    result = process_file("app/user_service.py", content)

    assert result is not None
    assert result["language"] == "python"
    assert "UserService" in result["classes"]
    assert "greet" in result["functions"]
    assert "helper" in result["functions"]
    assert "os" in result["imports"]


def test_parse_java_symbols():
    content = b"import java.util.List;\n\npublic class UserService {\n    public String greet(String name) {\n        return \"Hello \" + name;\n    }\n\n    private void run() {\n    }\n}\n"

    result = process_file("src/UserService.java", content)

    assert result is not None
    assert result["language"] == "java"
    assert "UserService" in result["classes"]
    assert "greet" in result["functions"]
    assert "run" in result["functions"]
    assert "java.util.List" in result["imports"]


def test_exclude_large_file():
    content = b"a" * 500001

    result = process_file("app/main.py", content)

    assert result is None

import re
from pathlib import PurePosixPath


SECRET_PATTERNS = (
    # Detect actual literal values assigned to sensitive configuration keys.
    re.compile(
        r"""(?i)\b(?:aws[_-]?access[_-]?key[_-]?id|aws[_-]?secret[_-]?access[_-]?key|github[_-]?token|openai[_-]?api[_-]?key|api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key|db[_-]?password|password)\b\s*[:=]\s*(?:['"](?P<quoted>[A-Za-z0-9/@#$%^&*!?+=_.-]{12,})['"]|(?P<plain>[A-Za-z0-9/@#$%^&*!?+=_-]{16,}))"""
    ),
    re.compile(
        r"""(?i)\bbearer\s+(?P<secret>[A-Za-z0-9'._~+/=-]{20,})"""
    ),
    re.compile(
        r"""(?i)(?P<secret>sk-(?:proj-)?[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"""
    ),
)


PLACEHOLDER_TOKENS = {
    "example",
    "placeholder",
    "your_",
    "your-",
    "changeme",
    "replace_me",
    "dummy",
    "demo",
    "sample",
}


# File ingestion limits

MAX_FILE_SIZE = 500_000
MAX_TOTAL_SIZE = 10 * 1024 * 1024
MAX_FILES = 200


# Allowed file extensions

ALLOWED_EXTENSIONS = {
    ".py", ".java", ".js", ".jsx", ".ts", ".tsx",
    ".html", ".css", ".json", ".md", ".txt",
    ".yml", ".yaml", ".toml", ".sql", ".sh",
    ".xml", ".properties", ".go", ".rs", ".c",
    ".cpp", ".h", ".hpp", ".cs", ".php", ".rb", ".kt",
}


# Directories to exclude

EXCLUDED_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv",
    "venv", "env", "dist", "build", ".next",
    ".pytest_cache", ".mypy_cache", ".idea",
    ".vscode", "coverage",
}


# Files to exclude

EXCLUDED_FILES = {
    ".env", ".env.local", ".env.production",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "uv.lock", "Cargo.lock",
    "Gemfile.lock", "composer.lock",
    "id_rsa", "id_ed25519", "authorized_keys",
}


# Binary and unnecessary extensions

EXCLUDED_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe",
    ".class", ".jar", ".war", ".zip", ".rar",
    ".7z", ".pdf", ".png", ".jpg", ".jpeg",
    ".gif", ".webp", ".mp3", ".mp4", ".log",
    ".db", ".sqlite", ".pem", ".key", ".p12", ".pfx",
}


def should_exclude_file(file_path: str) -> bool:

    path = PurePosixPath(file_path)
    file_name = path.name.lower()

    for part in path.parts:
        if part.lower() in EXCLUDED_DIRS:
            return True

    if file_name in EXCLUDED_FILES:
        return True

    if file_name.startswith(".env"):
        return True

    if path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True

    return False


def contains_sensitive_secret(text: str) -> bool:

    if not text:
        return False

    for pattern in SECRET_PATTERNS:

        for match in pattern.finditer(text):

            candidates = [
                value
                for value in match.groupdict().values()
                if value
            ]

            if not candidates:
                candidates = [match.group(0)]

            for candidate in candidates:

                value = candidate.strip().strip("\"'")

                if len(value) < 8:
                    continue

                normalized = value.lower()

                if any(
                    token in normalized
                    for token in PLACEHOLDER_TOKENS
                ):
                    continue

                return True

    return False


def normalize_file_text(content: bytes) -> str | None:

    try:

        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = content.decode("utf-16")

        elif content.startswith(b"\xef\xbb\xbf"):
            text = content.decode("utf-8-sig")

        else:
            text = content.decode("utf-8")

    except UnicodeDecodeError:
        return None

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")
    text = text.strip()

    if not text:
        return None

    return text


def filter_file(file_path: str, content: bytes) -> str | None:

    if should_exclude_file(file_path):
        return None

    if len(content) > MAX_FILE_SIZE:
        return None

    text = normalize_file_text(content)

    if text is None:
        return None

    if contains_sensitive_secret(text):
        return None

    return text

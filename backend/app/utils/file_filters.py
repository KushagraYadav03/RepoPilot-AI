
import re
from pathlib import PurePosixPath


SECRET_PATTERNS = (
    re.compile(
        r"(?i)(?:aws[\_-]?access[\_-]?key[\_-]?id|aws[\_-]?secret[\_-]?access[\_-]?key|github[\_-]?token|openai[\_-]?api[\_-]?key|api[\_-]?key|secret[\_-]?key|access[\_-]?token|client[\_-]?secret|private[\_-]?key|db[\_-]?password|password)[\s:=]+['\"]?([A-Za-z0-9/+=\-\.]{8,})['\"]?",
    ),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9'\-._~+/]+=*"),
    re.compile(r"(?i)(?:sk-(?:proj-)?[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"),
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
    ".py",
    ".java",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".sql",
    ".sh",
    ".xml",
    ".properties",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".kt",
}


# Directories to exclude

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    "coverage",
}


# Files to exclude

EXCLUDED_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "id_rsa",
    "id_ed25519",
    "authorized_keys",
}


# Binary and unnecessary extensions

EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".class",
    ".jar",
    ".war",
    ".zip",
    ".rar",
    ".7z",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".mp3",
    ".mp4",
    ".log",
    ".db",
    ".sqlite",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
}


def should_exclude_file(file_path: str) -> bool:

    path = PurePosixPath(file_path)

    file_name = path.name.lower()

    # Exclude unwanted directories.
    for part in path.parts:
        if part.lower() in EXCLUDED_DIRS:
            return True

    # Exclude specific files.
    if file_name in EXCLUDED_FILES:
        return True

    # Exclude all environment files.
    if file_name.startswith(".env"):
        return True

    # Exclude private key and certificate extensions.
    if path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True

    return False


def contains_sensitive_secret(text: str) -> bool:

    if not text:
        return False

    for pattern in SECRET_PATTERNS:

        matches = pattern.findall(text)

        for match in matches:

            if isinstance(match, tuple):
                candidates = []

                for part in match:
                    if part:
                        candidates.append(part)

            else:
                candidates = [match]

            for candidate in candidates:

                value = str(candidate).strip()
                value = value.strip("\"'")

                if not value:
                    continue

                if len(value) < 8:
                    continue

                normalized = value.lower()

                is_placeholder = False

                for token in PLACEHOLDER_TOKENS:
                    if token in normalized:
                        is_placeholder = True
                        break

                if is_placeholder:
                    continue

                return True

        search_result = pattern.search(text)

        if search_result:
            sanitized = search_result.group(0)
            sanitized = sanitized.lower()

            if "example" not in sanitized and "placeholder" not in sanitized:
                return True

    return False


def normalize_file_text(content: bytes) -> str | None:

    try:
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

from pathlib import PurePosixPath

from app.services.chunking_service import chunk_code
from app.services.code_parsing import parse_code_symbols
from app.utils.file_filters import filter_file


def process_file(file_path: str, content: bytes):
    text = filter_file(file_path, content)
    if text is None:
        return None

    path = PurePosixPath(file_path)
    parsed_metadata = parse_code_symbols(file_path, text)

    return {
        "file_path": file_path,
        "file_name": path.name,
        "extension": path.suffix.lower(),
        "content": text,
        "size": len(content),
        "line_count": len(text.splitlines()),
        "chunks": chunk_code(file_path, text),
        **parsed_metadata,
    }
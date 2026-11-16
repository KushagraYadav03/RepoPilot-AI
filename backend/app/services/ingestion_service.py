
import asyncio
import base64
import binascii
import hashlib
import logging
import uuid

from collections import defaultdict, deque
from urllib.parse import urlparse

import httpx

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.ingestion_job import IngestionJob
from app.models.repository import Repository
from app.models.repository_chunk import RepositoryChunk
from app.models.repository_file import RepositoryFile

from app.services.embedding_service import embed_repository_chunks
from app.services.file_processor import process_file
from app.services.git_service import fetch_github_tree

from app.services.qdrant_service import (
    delete_repository_points_by_ids,
    get_repository_file_point_ids,
    store_repository_embeddings,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# FILE CONTENT
# ---------------------------------------------------------

async def fetch_file_content(file_url: str) -> bytes:

    headers = {
        "User-Agent": "RepoPilot-AI",
        "Accept": "application/vnd.github+json",
    }

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=headers,
    ) as client:

        try:
            response = await client.get(file_url)

        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Unable to download GitHub file: "
                f"{file_url}. Error: {exc}"
            ) from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"GitHub file download failed. "
            f"HTTP: {response.status_code}. "
            f"URL: {file_url}. "
            f"Response: {response.text[:500]}"
        )

    raw_content = response.content

    try:
        payload = response.json()

    except (ValueError, UnicodeDecodeError):
        return raw_content

    if not isinstance(payload, dict):
        return raw_content

    if "sha" not in payload or "encoding" not in payload:
        return raw_content

    encoding = payload.get("encoding")
    content = payload.get("content")

    if not content:

        if payload.get("size", 0) == 0:
            return b""

        raise RuntimeError(
            f"GitHub returned empty blob content for {file_url}"
        )

    if encoding == "base64":

        try:
            encoded_content = "".join(content.split())

            decoded_content = base64.b64decode(
                encoded_content,
                validate=True,
            )

        except (binascii.Error, ValueError) as exc:
            raise RuntimeError(
                f"Invalid Base64 content returned by GitHub: "
                f"{file_url}"
            ) from exc

        expected_size = payload.get("size")

        if (
            expected_size is not None
            and len(decoded_content) != expected_size
        ):
            raise RuntimeError(
                f"Decoded file size mismatch for {file_url}. "
                f"Expected: {expected_size}, "
                f"Actual: {len(decoded_content)}"
            )

        return decoded_content

    if encoding == "utf-8":
        return content.encode("utf-8")

    raise RuntimeError(
        f"Unsupported GitHub blob encoding: {encoding}"
    )


# ---------------------------------------------------------
# QDRANT HELPERS
# ---------------------------------------------------------

async def _get_qdrant_file_point_ids(
    repository_id: int,
    file_path: str,
) -> list[str]:

    return await asyncio.to_thread(
        get_repository_file_point_ids,
        repository_id=repository_id,
        file_path=file_path,
    )


async def _delete_qdrant_points(
    point_ids: list[str],
) -> bool:

    if not point_ids:
        return True

    return await asyncio.to_thread(
        delete_repository_points_by_ids,
        point_ids=point_ids,
    )


async def _cleanup_new_points(
    point_ids: list[str],
) -> None:

    if not point_ids:
        return

    try:
        deleted = await _delete_qdrant_points(point_ids)

        if not deleted:
            logger.error(
                "Unable to cleanup newly inserted Qdrant points: %s",
                point_ids,
            )

    except Exception:
        logger.exception(
            "Failed to cleanup newly inserted Qdrant points"
        )


def _expected_qdrant_point_ids(
    existing_chunks: list,
) -> set[str]:
    """
    Generate expected deterministic Qdrant IDs
    from actual PostgreSQL chunk IDs.
    """

    expected_ids = set()

    for chunk in existing_chunks:

        if chunk.id is None:
            raise RuntimeError(
                "PostgreSQL chunk has no database ID."
            )

        expected_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"repopilot-point-id:{chunk.id}",
            )
        )

        expected_ids.add(expected_id)

    return expected_ids


def _check_qdrant_consistency(
    existing_chunks: list,
    actual_point_ids: list[str],
    file_path: str,
) -> bool:
    """
    Compare expected PostgreSQL-derived UUIDs
    with actual Qdrant point IDs.
    """

    expected_ids = _expected_qdrant_point_ids(
        existing_chunks
    )

    actual_ids = set(actual_point_ids)

    is_consistent = expected_ids == actual_ids

    if not is_consistent:

        missing_ids = expected_ids - actual_ids
        obsolete_ids = actual_ids - expected_ids

        logger.warning(
            "Qdrant inconsistency for %s. "
            "Expected: %s, Actual: %s, Missing: %s, "
            "Obsolete: %s",
            file_path,
            len(expected_ids),
            len(actual_ids),
            len(missing_ids),
            len(obsolete_ids),
        )

    return is_consistent


# ---------------------------------------------------------
# CHUNK METADATA
# ---------------------------------------------------------

def _attach_chunk_commit_metadata(
    file_chunks: list[dict],
    commit_sha: str | None,
) -> None:

    for chunk in file_chunks:

        if not isinstance(chunk, dict):
            raise TypeError(
                "Every repository chunk must be a dictionary."
            )

        if not chunk.get("commit_sha"):
            chunk["commit_sha"] = commit_sha


def _chunk_identity(chunk: dict) -> tuple:

    return (
        str(chunk.get("file_path") or "").strip(),
        str(chunk.get("symbol_name") or "").strip(),
        str(chunk.get("symbol_kind") or "").strip(),
        chunk.get("start_line"),
        chunk.get("end_line"),
        str(chunk.get("content") or "").strip(),
    )


def _normalize_file_chunks(
    file_chunks: list[dict],
    file_path: str,
) -> None:

    for chunk in file_chunks:

        if not isinstance(chunk, dict):
            raise TypeError(
                "Every repository chunk must be a dictionary."
            )

        chunk["file_path"] = (
            chunk.get("file_path") or file_path
        )

        chunk["symbol_name"] = (
            chunk.get("symbol_name") or "unknown"
        )

        chunk["symbol_kind"] = (
            chunk.get("symbol_kind") or "unknown"
        )

        chunk["start_line"] = (
            chunk.get("start_line")
            if chunk.get("start_line") is not None
            else 1
        )

        chunk["end_line"] = (
            chunk.get("end_line")
            if chunk.get("end_line") is not None
            else 1
        )

        chunk["content"] = chunk.get("content") or ""


# ---------------------------------------------------------
# EMBEDDING METADATA
# ---------------------------------------------------------

def _attach_embedding_metadata(
    source_chunks: list[dict],
    embedded_chunks: list[dict],
) -> None:

    source_lookup = {}

    for source_chunk in source_chunks:

        if not isinstance(source_chunk, dict):
            raise TypeError(
                "Every source chunk must be a dictionary."
            )

        identity = _chunk_identity(source_chunk)

        source_lookup.setdefault(
            identity,
            source_chunk,
        )

    metadata_fields = (
        "file_path",
        "symbol_name",
        "symbol_kind",
        "start_line",
        "end_line",
        "commit_sha",
        "content",
    )

    for embedded_chunk in embedded_chunks:

        if not isinstance(embedded_chunk, dict):
            raise TypeError(
                "Every embedded chunk must be a dictionary."
            )

        identity = _chunk_identity(embedded_chunk)

        source_chunk = source_lookup.get(identity)

        if source_chunk is None:
            raise RuntimeError(
                "Unable to match an embedded chunk with "
                f"its source metadata: {identity}"
            )

        metadata = embedded_chunk.get("metadata") or {}

        if not isinstance(metadata, dict):
            raise TypeError(
                "Embedding metadata must be a dictionary."
            )

        metadata = dict(metadata)

        for field in metadata_fields:

            value = source_chunk.get(field)

            if value is None:
                continue

            if embedded_chunk.get(field) is None:
                embedded_chunk[field] = value

            if metadata.get(field) is None:
                metadata[field] = value

        embedded_chunk["metadata"] = metadata


# ---------------------------------------------------------
# ATTACH EXISTING POSTGRESQL IDs
# ---------------------------------------------------------

def _attach_existing_chunk_ids(
    existing_chunks: list,
    embedded_chunks: list[dict],
) -> None:
    """
    Reuse existing PostgreSQL IDs when file content
    has not changed and only Qdrant needs repair.

    No PostgreSQL chunk recreation is performed.
    """

    records_by_identity = defaultdict(deque)

    for record in existing_chunks:

        records_by_identity[
            _chunk_identity({
                "file_path": record.file_path,
                "symbol_name": record.symbol_name,
                "symbol_kind": record.symbol_kind,
                "start_line": record.start_line,
                "end_line": record.end_line,
                "content": record.content,
            })
        ].append(record)

    for embedded_chunk in embedded_chunks:

        identity = _chunk_identity(embedded_chunk)

        matching_records = records_by_identity.get(identity)

        if not matching_records:
            raise RuntimeError(
                "Unable to match embedded chunk with "
                f"existing PostgreSQL record: {identity}"
            )

        record = matching_records.popleft()

        if record.id is None:
            raise RuntimeError(
                "Existing PostgreSQL chunk has no ID."
            )

        embedded_chunk["id"] = record.id
        embedded_chunk["repository_chunk_id"] = record.id

        metadata = dict(
            embedded_chunk.get("metadata") or {}
        )

        metadata["repository_chunk_id"] = record.id

        embedded_chunk["metadata"] = metadata

    remaining = sum(
        len(records)
        for records in records_by_identity.values()
    )

    if remaining:
        raise RuntimeError(
            f"{remaining} existing PostgreSQL chunks "
            "were not matched with generated embeddings."
        )


# ---------------------------------------------------------
# INSERT NEW POSTGRESQL CHUNKS AND ATTACH IDs
# ---------------------------------------------------------

def _insert_chunks_and_attach_ids(
    db,
    repository_id: int,
    file_chunks: list[dict],
    embedded_chunks: list[dict],
) -> None:

    records_by_identity = defaultdict(deque)

    for chunk in file_chunks:

        record = RepositoryChunk(
            repository_id=repository_id,
            file_path=chunk["file_path"],
            symbol_name=chunk["symbol_name"],
            symbol_kind=chunk["symbol_kind"],
            start_line=chunk["start_line"],
            end_line=chunk["end_line"],
            content=chunk["content"],
            commit_sha=chunk.get("commit_sha"),
        )

        db.add(record)

        records_by_identity[
            _chunk_identity(chunk)
        ].append(record)

    db.flush()

    for embedded_chunk in embedded_chunks:

        identity = _chunk_identity(embedded_chunk)

        matching_records = records_by_identity.get(identity)

        if not matching_records:
            raise RuntimeError(
                "Unable to match embedded chunk to its "
                f"PostgreSQL row: {identity}"
            )

        record = matching_records.popleft()

        if record.id is None:
            raise RuntimeError(
                "PostgreSQL did not assign an ID "
                "to a repository chunk."
            )

        embedded_chunk["id"] = record.id
        embedded_chunk["repository_chunk_id"] = record.id

        metadata = dict(
            embedded_chunk.get("metadata") or {}
        )

        metadata["repository_chunk_id"] = record.id

        embedded_chunk["metadata"] = metadata

    remaining = sum(
        len(records)
        for records in records_by_identity.values()
    )

    if remaining:
        raise RuntimeError(
            f"{remaining} PostgreSQL chunks were not "
            "matched with generated embeddings."
        )


# ---------------------------------------------------------
# MAIN INGESTION
# ---------------------------------------------------------

async def process_ingestion_job(job_id: int):

    with SessionLocal() as db:

        job = db.get(IngestionJob, job_id)

        if job is None:
            logger.error(
                "Ingestion job %s not found",
                job_id,
            )
            return

        pending_new_point_ids = []
        obsolete_point_ids = []

        try:

            job.status = "processing"
            job.error_message = None

            db.commit()

            repository = db.scalar(
                select(Repository).where(
                    Repository.id == job.repository_id,
                    Repository.owner_id == job.user_id,
                )
            )

            if repository is None:
                raise ValueError(
                    "Repository not found or access denied"
                )

            parsed_url = urlparse(
                str(repository.github_url)
            )

            if parsed_url.hostname not in {
                "github.com",
                "www.github.com",
            }:
                raise ValueError(
                    "Invalid GitHub repository URL"
                )

            path_parts = [
                part
                for part in parsed_url.path.split("/")
                if part
            ]

            if len(path_parts) != 2:
                raise ValueError(
                    "Invalid GitHub repository URL"
                )

            owner = path_parts[0]
            repo = path_parts[1].removesuffix(".git")

            if not owner or not repo:
                raise ValueError(
                    "Invalid GitHub repository URL"
                )

            logger.info(
                "Starting ingestion job %s for %s/%s",
                job_id,
                owner,
                repo,
            )

            tree_data = await fetch_github_tree(
                owner=owner,
                repo=repo,
            )

            job.default_branch = tree_data["default_branch"]
            job.tree_sha = tree_data["tree_sha"]

            repository.default_branch = (
                tree_data.get("default_branch")
                or repository.default_branch
            )

            repository.tree_sha = (
                tree_data.get("tree_sha")
                or repository.tree_sha
            )

            repository.last_commit_sha = (
                tree_data.get("latest_commit_sha")
                or repository.last_commit_sha
            )

            current_commit_sha = repository.last_commit_sha

            languages = tree_data.get("languages") or []

            if languages:
                repository.programming_languages = ", ".join(
                    sorted(set(languages))
                )

            files = tree_data.get("files", [])

            unique_files = []
            seen_paths = set()

            for file_info in files:

                file_path = file_info["path"]

                if file_path in seen_paths:
                    logger.warning(
                        "Skipping duplicate file path: %s",
                        file_path,
                    )
                    continue

                seen_paths.add(file_path)
                unique_files.append(file_info)

            job.total_files = len(unique_files)

            processed_count = 0
            current_paths = set(seen_paths)

            # -------------------------------------------------
            # PROCESS EACH FILE
            # -------------------------------------------------

            for file_info in unique_files:

                file_path = file_info["path"]
                file_url = file_info["url"]

                logger.info(
                    "Processing file %s in job %s",
                    file_path,
                    job_id,
                )

                file_content = await fetch_file_content(
                    file_url
                )

                processed_file = process_file(
                    file_path,
                    file_content,
                )

                if processed_file is None:

                    processed_count += 1
                    job.processed_files = processed_count

                    continue

                file_path_value = processed_file.get(
                    "file_path",
                    file_path,
                )

                current_paths.add(file_path_value)

                file_name_value = (
                    processed_file.get("file_name")
                    or file_path_value.rsplit("/", 1)[-1]
                )

                extension_value = processed_file.get(
                    "extension"
                )

                content_value = (
                    processed_file.get("content") or ""
                )

                content_bytes = content_value.encode("utf-8")

                file_hash = hashlib.sha256(
                    content_bytes
                ).hexdigest()

                size_value = processed_file.get(
                    "size",
                    len(content_bytes),
                )

                line_count_value = processed_file.get(
                    "line_count",
                    0,
                )

                existing_file = db.scalar(
                    select(RepositoryFile).where(
                        RepositoryFile.repository_id
                        == job.repository_id,
                        RepositoryFile.file_path
                        == file_path_value,
                    )
                )

                existing_chunks = db.scalars(
                    select(RepositoryChunk).where(
                        RepositoryChunk.repository_id
                        == job.repository_id,
                        RepositoryChunk.file_path
                        == file_path_value,
                    )
                ).all()

                # Determine whether PostgreSQL file content
                # is unchanged.
                file_unchanged = (
                    existing_file is not None
                    and existing_file.file_hash == file_hash
                )

                # Always inspect Qdrant, even for unchanged files.
                old_point_ids = (
                    await _get_qdrant_file_point_ids(
                        repository_id=job.repository_id,
                        file_path=file_path_value,
                    )
                )

                # Compare actual Qdrant IDs with expected UUID5 IDs.
                qdrant_is_consistent = (
                    _check_qdrant_consistency(
                        existing_chunks=existing_chunks,
                        actual_point_ids=old_point_ids,
                        file_path=file_path_value,
                    )
                )

                # Skip only when both systems are consistent.
                if file_unchanged and qdrant_is_consistent:

                    processed_count += 1
                    job.processed_files = processed_count

                    logger.info(
                        "Skipping unchanged and consistent file %s",
                        file_path_value,
                    )

                    continue

                if file_unchanged:

                    logger.warning(
                        "Qdrant repair required for unchanged file %s",
                        file_path_value,
                    )

                # -------------------------------------------------
                # NORMALIZE CHUNKS
                # -------------------------------------------------

                file_chunks = (
                    processed_file.get("chunks") or []
                )

                _normalize_file_chunks(
                    file_chunks,
                    file_path_value,
                )

                _attach_chunk_commit_metadata(
                    file_chunks,
                    current_commit_sha,
                )

                embedded_chunks = []
                stored_ids = []

                # -------------------------------------------------
                # GENERATE EMBEDDINGS
                # -------------------------------------------------

                if file_chunks:

                    embedded_chunks = await asyncio.to_thread(
                        embed_repository_chunks,
                        file_chunks,
                    )

                    if not embedded_chunks:
                        raise RuntimeError(
                            f"No embeddings generated for "
                            f"{file_path_value}"
                        )

                    _attach_embedding_metadata(
                        file_chunks,
                        embedded_chunks,
                    )

                # -------------------------------------------------
                # UPDATE REPOSITORY FILE
                # -------------------------------------------------

                if not file_unchanged:

                    if existing_file is not None:

                        existing_file.file_name = file_name_value
                        existing_file.file_hash = file_hash
                        existing_file.extension = extension_value
                        existing_file.content = content_value
                        existing_file.size = size_value
                        existing_file.line_count = line_count_value
                        existing_file.ingestion_job_id = job.id

                    else:

                        db.add(
                            RepositoryFile(
                                repository_id=job.repository_id,
                                ingestion_job_id=job.id,
                                file_path=file_path_value,
                                file_name=file_name_value,
                                file_hash=file_hash,
                                extension=extension_value,
                                content=content_value,
                                size=size_value,
                                line_count=line_count_value,
                            )
                        )

                # -------------------------------------------------
                # ATTACH POSTGRESQL CHUNK IDs
                # -------------------------------------------------

                if file_chunks:

                    if file_unchanged:

                        # Preserve existing PostgreSQL chunk IDs.
                        _attach_existing_chunk_ids(
                            existing_chunks=existing_chunks,
                            embedded_chunks=embedded_chunks,
                        )

                    else:

                        # Replace PostgreSQL chunks only when
                        # actual file content has changed.
                        for old_chunk in existing_chunks:
                            db.delete(old_chunk)

                        _insert_chunks_and_attach_ids(
                            db=db,
                            repository_id=job.repository_id,
                            file_chunks=file_chunks,
                            embedded_chunks=embedded_chunks,
                        )

                elif not file_unchanged:

                    for old_chunk in existing_chunks:
                        db.delete(old_chunk)

                # -------------------------------------------------
                # STORE QDRANT POINTS
                # -------------------------------------------------

                if embedded_chunks:

                    stored_ids = await asyncio.to_thread(
                        store_repository_embeddings,
                        embedded_chunks,
                        repository_id=job.repository_id,
                    )

                    if not stored_ids:
                        raise RuntimeError(
                            f"Qdrant failed to store embeddings "
                            f"for {file_path_value}"
                        )

                    if len(stored_ids) != len(embedded_chunks):
                        raise RuntimeError(
                            f"Qdrant stored {len(stored_ids)} vectors, "
                            f"but {len(embedded_chunks)} were generated "
                            f"for {file_path_value}"
                        )

                    # Track newly introduced point IDs for rollback cleanup.
                    pending_new_point_ids.extend(
                        point_id
                        for point_id in stored_ids
                        if point_id not in old_point_ids
                    )

                # -------------------------------------------------
                # IDENTIFY OBSOLETE QDRANT POINTS
                # -------------------------------------------------

                new_point_ids = set(stored_ids)

                file_obsolete_ids = [
                    point_id
                    for point_id in old_point_ids
                    if point_id not in new_point_ids
                ]

                obsolete_point_ids.extend(
                    file_obsolete_ids
                )

                processed_count += 1
                job.processed_files = processed_count

                logger.info(
                    "Processed %s/%s files: %s",
                    processed_count,
                    job.total_files,
                    file_path_value,
                )

            # -----------------------------------------------------
            # REMOVE FILES DELETED FROM GITHUB
            # -----------------------------------------------------

            existing_files = db.scalars(
                select(RepositoryFile).where(
                    RepositoryFile.repository_id
                    == job.repository_id,
                )
            ).all()

            deleted_file_point_ids = []

            for existing_file in existing_files:

                if existing_file.file_path not in current_paths:

                    old_ids = await _get_qdrant_file_point_ids(
                        repository_id=job.repository_id,
                        file_path=existing_file.file_path,
                    )

                    deleted_file_point_ids.extend(old_ids)

                    db.delete(existing_file)

            # -----------------------------------------------------
            # REMOVE STALE POSTGRESQL CHUNKS
            # -----------------------------------------------------

            stale_chunks = db.scalars(
                select(RepositoryChunk).where(
                    RepositoryChunk.repository_id
                    == job.repository_id,
                )
            ).all()

            for stale_chunk in stale_chunks:

                if stale_chunk.file_path not in current_paths:
                    db.delete(stale_chunk)

            obsolete_point_ids.extend(
                deleted_file_point_ids
            )

            # -----------------------------------------------------
            # COMMIT POSTGRESQL
            # -----------------------------------------------------

            job.processed_files = processed_count
            job.status = "completed"
            job.error_message = None

            db.commit()

            # PostgreSQL commit succeeded.
            pending_new_point_ids.clear()

            # -----------------------------------------------------
            # DELETE OBSOLETE QDRANT POINTS
            # -----------------------------------------------------

            if obsolete_point_ids:

                deleted = await _delete_qdrant_points(
                    list(set(obsolete_point_ids))
                )

                if not deleted:

                    logger.error(
                        "Unable to delete obsolete Qdrant points "
                        "for ingestion job %s",
                        job_id,
                    )

            logger.info(
                "Ingestion job %s completed. "
                "Total files: %s, processed: %s",
                job_id,
                tree_data.get("total_files", len(files)),
                processed_count,
            )

        except Exception as exc:

            db.rollback()

            await _cleanup_new_points(
                pending_new_point_ids
            )

            logger.exception(
                "Ingestion job %s failed",
                job_id,
            )

            failed_job = db.get(
                IngestionJob,
                job_id,
            )

            if failed_job is not None:

                failed_job.status = "failed"
                failed_job.error_message = str(exc)[:4000]

                db.commit()


import asyncio
import hashlib
import logging
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
    update_repository_file_commit_sha,
)


logger = logging.getLogger(__name__)


async def fetch_file_content(file_url: str) -> bytes:
    """Download actual raw file content from GitHub."""

    headers = {"User-Agent": "RepoPilot-AI"}

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=headers,
    ) as client:
        try:
            response = await client.get(file_url)
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Unable to connect while downloading file: "
                f"{file_url}. Error: {exc}"
            ) from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"File download failed. "
            f"HTTP status: {response.status_code}. "
            f"URL: {file_url}. "
            f"Response: {response.text[:500]}"
        )

    return response.content


async def _get_qdrant_file_point_ids(
    repository_id: int,
    file_path: str,
) -> list[str]:
    """Retrieve existing Qdrant point IDs for one file."""

    return await asyncio.to_thread(
        get_repository_file_point_ids,
        repository_id=repository_id,
        file_path=file_path,
    )


async def _delete_qdrant_points(
    point_ids: list[str],
) -> bool:
    """Delete only the specified Qdrant point IDs."""

    if not point_ids:
        return True

    return await asyncio.to_thread(
        delete_repository_points_by_ids,
        point_ids=point_ids,
    )


async def _cleanup_new_points(
    point_ids: list[str],
) -> None:
    """Best-effort cleanup of newly inserted Qdrant points."""

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


def _attach_chunk_commit_metadata(
    file_chunks: list[dict],
    commit_sha: str | None,
) -> None:
    """Attach repository snapshot commit SHA to source chunks."""

    for chunk in file_chunks:
        if not isinstance(chunk, dict):
            raise TypeError(
                "Every repository chunk must be a dictionary."
            )

        if not chunk.get("commit_sha"):
            chunk["commit_sha"] = commit_sha


def _attach_embedding_metadata(
    source_chunks: list[dict],
    embedded_chunks: list[dict],
) -> None:
    """Preserve source metadata in embedding output."""

    if len(source_chunks) != len(embedded_chunks):
        raise RuntimeError(
            "The number of generated embeddings does not match "
            "the number of source chunks."
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

    for source_chunk, embedded_chunk in zip(
        source_chunks,
        embedded_chunks,
    ):
        if not isinstance(embedded_chunk, dict):
            raise TypeError(
                "Every embedded chunk must be a dictionary."
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

            current_commit_sha = (
                repository.last_commit_sha
            )

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

                file_content_unchanged = (
                    existing_file is not None
                    and getattr(
                        existing_file,
                        "file_hash",
                        "",
                    ) == file_hash
                )

                # Update missing commit SHA for unchanged files.
                if file_content_unchanged:

                    if current_commit_sha:

                        # Update commit SHA in Qdrant.
                        await asyncio.to_thread(
                            update_repository_file_commit_sha,
                            repository_id=job.repository_id,
                            file_path=file_path_value,
                            commit_sha=current_commit_sha,
                        )

                        # Update only missing commit SHA
                        # in PostgreSQL chunks.
                        for existing_chunk in existing_chunks:

                            if not existing_chunk.commit_sha:
                                existing_chunk.commit_sha = (
                                    current_commit_sha
                                )

                    chunks_have_current_commit = all(
                        chunk.commit_sha == current_commit_sha
                        for chunk in existing_chunks
                    )

                    if chunks_have_current_commit:

                        processed_count += 1
                        job.processed_files = processed_count

                        logger.info(
                            "Skipping unchanged file after "
                            "citation metadata update: %s",
                            file_path_value,
                        )
                        continue

                old_point_ids = (
                    await _get_qdrant_file_point_ids(
                        repository_id=job.repository_id,
                        file_path=file_path_value,
                    )
                )

                file_chunks = (
                    processed_file.get("chunks") or []
                )

                _attach_chunk_commit_metadata(
                    file_chunks,
                    current_commit_sha,
                )

                embedded_chunks = []
                stored_ids = []

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

                    stored_ids = await asyncio.to_thread(
                        store_repository_embeddings,
                        embedded_chunks,
                        repository_id=job.repository_id,
                    )

                    if not stored_ids:
                        raise RuntimeError(
                            f"Qdrant failed to store embeddings for "
                            f"{file_path_value}"
                        )

                    if len(stored_ids) != len(embedded_chunks):
                        pending_new_point_ids.extend(
                            point_id
                            for point_id in stored_ids
                            if point_id not in old_point_ids
                        )

                        raise RuntimeError(
                            f"Qdrant stored {len(stored_ids)} vectors, "
                            f"but {len(embedded_chunks)} were generated "
                            f"for {file_path_value}"
                        )

                    pending_new_point_ids.extend(
                        point_id
                        for point_id in stored_ids
                        if point_id not in old_point_ids
                    )

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

                for old_chunk in existing_chunks:
                    db.delete(old_chunk)

                for chunk in file_chunks:

                    db.add(
                        RepositoryChunk(
                            repository_id=job.repository_id,
                            file_path=chunk.get(
                                "file_path",
                                file_path_value,
                            ),
                            symbol_name=(
                                chunk.get("symbol_name")
                                or "unknown"
                            ),
                            symbol_kind=(
                                chunk.get("symbol_kind")
                                or "unknown"
                            ),
                            start_line=(
                                chunk.get("start_line")
                                if chunk.get("start_line") is not None
                                else 1
                            ),
                            end_line=(
                                chunk.get("end_line")
                                if chunk.get("end_line") is not None
                                else 1
                            ),
                            content=chunk.get("content") or "",
                            commit_sha=chunk.get(
                                "commit_sha"
                            ),
                        )
                    )

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
                    "Processed %s/%s files",
                    processed_count,
                    job.total_files,
                )

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

            job.processed_files = processed_count
            job.status = "completed"
            job.error_message = None

            db.commit()

            pending_new_point_ids.clear()

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

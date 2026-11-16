import argparse
import json
import math
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
)

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.repository_chunk import RepositoryChunk
from app.services.embedding_service import embed_repository_chunks


REPOSITORY_ID = 1
SCROLL_BATCH_SIZE = 100
CHECKPOINT_VERSION = 2
EMBEDDING_TASK_TYPE = "RETRIEVAL_DOCUMENT"


def point_id_for_chunk(chunk_id: int) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"repopilot-point-id:{chunk_id}",
    ))


def identity(
    file_path,
    symbol_name,
    symbol_kind,
    start_line,
    end_line,
    content,
):
    return (
        str(file_path or "").strip(),
        str(symbol_name or "").strip(),
        str(symbol_kind or "").strip(),
        int(start_line) if start_line is not None else None,
        int(end_line) if end_line is not None else None,
        str(content or "").strip(),
    )


def validate_vector(vector, chunk_id, dimension):
    if not isinstance(vector, (list, tuple)) or not vector:
        raise RuntimeError(
            f"Invalid vector for chunk {chunk_id}"
        )

    try:
        result = [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Non-numeric vector for chunk {chunk_id}"
        ) from exc

    if len(result) != dimension:
        raise RuntimeError(
            f"Dimension mismatch for chunk {chunk_id}: "
            f"expected {dimension}, got {len(result)}"
        )

    if not all(math.isfinite(value) for value in result):
        raise RuntimeError(
            f"NaN or infinity in vector for chunk {chunk_id}"
        )

    return result


def scroll_repository(client, collection_name):
    scroll_filter = Filter(
        must=[
            FieldCondition(
                key="repository_id",
                match=MatchValue(value=REPOSITORY_ID),
            )
        ]
    )

    records = []
    offset = None

    while True:
        batch, next_offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            limit=SCROLL_BATCH_SIZE,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )

        records.extend(batch)

        if next_offset is None:
            return records

        offset = next_offset


def db_identity(chunk):
    return identity(
        chunk.file_path,
        chunk.symbol_name,
        chunk.symbol_kind,
        chunk.start_line,
        chunk.end_line,
        chunk.content,
    )


def qdrant_identity(record):
    payload = record.payload or {}
    metadata = payload.get("metadata") or {}

    def value(key):
        return payload.get(key, metadata.get(key))

    return identity(
        value("file_path"),
        value("symbol_name"),
        value("symbol_kind"),
        value("start_line"),
        value("end_line"),
        value("content"),
    )


def make_payload(chunk, embedding_text):
    metadata = {
        "repository_chunk_id": chunk["id"],
        "repository_id": REPOSITORY_ID,
        "file_path": chunk["file_path"],
        "symbol_name": chunk["symbol_name"],
        "symbol_kind": chunk["symbol_kind"],
        "start_line": chunk["start_line"],
        "end_line": chunk["end_line"],
        "content": chunk["content"],
        "commit_sha": chunk["commit_sha"],
        "embedding_model": settings.embedding_model.removeprefix(
            "models/"
        ),
        "embedding_task_type": EMBEDDING_TASK_TYPE,
    }

    return {
        "repository_id": REPOSITORY_ID,
        "repository_chunk_id": chunk["id"],
        "file_path": chunk["file_path"],
        "symbol_name": chunk["symbol_name"],
        "symbol_kind": chunk["symbol_kind"],
        "start_line": chunk["start_line"],
        "end_line": chunk["end_line"],
        "content": chunk["content"],
        "embedding_text": embedding_text,
        "commit_sha": chunk["commit_sha"],
        "embedding_model": settings.embedding_model.removeprefix(
            "models/"
        ),
        "embedding_task_type": EMBEDDING_TASK_TYPE,
        "metadata": metadata,
    }


def atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")

    temp_path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    temp_path.replace(path)


def save_checkpoint(path, embeddings):
    atomic_write_json(path, {
        "version": CHECKPOINT_VERSION,
        "repository_id": REPOSITORY_ID,
        "model_name": settings.embedding_model.removeprefix(
            "models/"
        ),
        "task_type": EMBEDDING_TASK_TYPE,
        "updated_at": datetime.now().isoformat(),
        "embeddings": embeddings,
    })


def load_checkpoint(path, chunks, dimension):
    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Cannot read checkpoint: {path}"
        ) from exc

    if data.get("version") != CHECKPOINT_VERSION:
        raise RuntimeError("Checkpoint version mismatch.")

    if data.get("repository_id") != REPOSITORY_ID:
        raise RuntimeError("Wrong repository checkpoint.")

    if data.get("model_name") != settings.embedding_model.removeprefix(
        "models/"
    ):
        raise RuntimeError("Checkpoint model mismatch.")

    if data.get("task_type") != EMBEDDING_TASK_TYPE:
        raise RuntimeError("Checkpoint task type mismatch.")

    expected = {
        str(chunk["id"]): chunk
        for chunk in chunks
    }

    cached = {}

    for chunk_id, item in data.get("embeddings", {}).items():
        chunk = expected.get(str(chunk_id))

        if chunk is None:
            continue

        if item.get("identity") != list(chunk["identity"]):
            continue

        vector = validate_vector(
            item.get("embedding"),
            chunk_id,
            dimension,
        )

        cached[int(chunk_id)] = {
            "identity": list(chunk["identity"]),
            "embedding": vector,
            "text": item.get("text", ""),
        }

    return cached


def verify_target_points(
    client,
    collection_name,
    expected,
    dimension,
):
    records = scroll_repository(
        client,
        collection_name,
    )

    by_id = {
        str(record.id): record
        for record in records
    }

    missing = set(expected) - set(by_id)

    if missing:
        raise RuntimeError(
            f"Verification failed: {len(missing)} target points missing."
        )

    for point_id, data in expected.items():
        record = by_id[point_id]
        payload = record.payload or {}

        if int(
            payload.get("repository_chunk_id", -1)
        ) != data["chunk_id"]:
            raise RuntimeError(
                f"Wrong chunk ID: {point_id}"
            )

        if qdrant_identity(record) != data["identity"]:
            raise RuntimeError(
                f"Identity mismatch: {point_id}"
            )

        if payload.get("embedding_model") != data["model"]:
            raise RuntimeError(
                f"Embedding model mismatch: {point_id}"
            )

        if payload.get("embedding_task_type") != EMBEDDING_TASK_TYPE:
            raise RuntimeError(
                f"Embedding task type mismatch: {point_id}"
            )

        validate_vector(
            record.vector,
            data["chunk_id"],
            dimension,
        )

    return records


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform actual repair.",
    )

    parser.add_argument(
        "--checkpoint",
        default=(
            ".qdrant_repair_checkpoint_repo_1_full_reembed_v2.json"
        ),
    )

    args = parser.parse_args()

    qdrant_path = Path(
        settings.qdrant_path
    ).expanduser().resolve()

    collection_name = settings.qdrant_collection

    checkpoint_path = Path(
        args.checkpoint
    ).expanduser().resolve()

    model_name = settings.embedding_model.removeprefix(
        "models/"
    )

    print("\n========== QDRANT FULL RE-EMBED REPAIR ==========")
    print("Repository:", REPOSITORY_ID)
    print("Qdrant path:", qdrant_path)
    print("Collection:", collection_name)
    print("Model:", model_name)
    print("Task type:", EMBEDDING_TASK_TYPE)
    print("Checkpoint:", checkpoint_path)
    print("Mode:", "APPLY" if args.apply else "DRY RUN")

    if not qdrant_path.exists():
        raise RuntimeError("Qdrant directory does not exist.")

    # STEP 1: READ POSTGRESQL

    with SessionLocal() as db:
        orm_chunks = db.scalars(
            select(RepositoryChunk)
            .where(
                RepositoryChunk.repository_id == REPOSITORY_ID
            )
            .order_by(RepositoryChunk.id)
        ).all()

        chunks = [
            {
                "id": c.id,
                "file_path": c.file_path,
                "symbol_name": c.symbol_name,
                "symbol_kind": c.symbol_kind,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "content": c.content or "",
                "commit_sha": c.commit_sha,
                "identity": db_identity(c),
            }
            for c in orm_chunks
        ]

    if not chunks:
        raise RuntimeError("No PostgreSQL chunks found.")

    chunk_ids = [chunk["id"] for chunk in chunks]

    if len(chunk_ids) != len(set(chunk_ids)):
        raise RuntimeError("Duplicate PostgreSQL chunk IDs.")

    if any(not chunk["content"].strip() for chunk in chunks):
        raise RuntimeError("Empty PostgreSQL chunk content found.")

    print("\nPostgreSQL chunks:", len(chunks))

    # STEP 2: INSPECT QDRANT

    client = QdrantClient(path=str(qdrant_path))

    try:
        if not client.collection_exists(collection_name):
            raise RuntimeError(
                f"Collection {collection_name} does not exist."
            )

        old_records = scroll_repository(
            client,
            collection_name,
        )

        collection = client.get_collection(collection_name)
        vector_config = collection.config.params.vectors

        if isinstance(vector_config, dict):
            raise RuntimeError(
                "Named vectors are not supported by this repair script."
            )

        vector_dimension = vector_config.size

    finally:
        client.close()

    print("Existing Qdrant points:", len(old_records))
    print("Qdrant vector dimension:", vector_dimension)

    # DYNAMIC DIMENSION CHECK: Check against settings.embedding_dimension (768 for Jina)
    if vector_dimension != settings.embedding_dimension:
        raise RuntimeError(
            f"Expected {settings.embedding_dimension} dimensions, got {vector_dimension}."
        )

    # STEP 3: DRY RUN

    if not args.apply:
        print("\n========== REPAIR PLAN ==========")
        print("Fresh embeddings required:", len(chunks))
        print("Old vectors to reuse: 0")
        print(
            "Old repository points to replace:",
            len(old_records),
        )
        print("Expected final points:", len(chunks))
        print("\nDRY RUN COMPLETE.")
        print("No embeddings generated.")
        print("No Qdrant changes made.")
        print("\nReview the plan before running --apply.")
        return

    # STEP 4: LOAD CHECKPOINT FOR ALL CHUNKS

    cached = load_checkpoint(
        checkpoint_path,
        chunks,
        vector_dimension,
    )

    chunks_by_id = {
        chunk["id"]: chunk
        for chunk in chunks
    }

    pending_chunks = [
        chunk
        for chunk in chunks
        if chunk["id"] not in cached
    ]

    print("\n========== EMBEDDING PLAN ==========")
    print("Total chunks:", len(chunks))
    print("Valid checkpoint embeddings:", len(cached))
    print("New embeddings to generate:", len(pending_chunks))

    checkpoint_embeddings = {
        str(chunk_id): item
        for chunk_id, item in cached.items()
    }

    def on_batch_complete(batch_results, completed, total):
        for item in batch_results:
            chunk_id = item.get("repository_chunk_id")

            if chunk_id is None:
                raise RuntimeError(
                    "Embedding result lost PostgreSQL chunk ID."
                )

            chunk_id = int(chunk_id)
            chunk = chunks_by_id.get(chunk_id)

            if chunk is None:
                raise RuntimeError(
                    f"Unexpected chunk ID: {chunk_id}"
                )

            vector = validate_vector(
                item["embedding"],
                chunk_id,
                vector_dimension,
            )

            checkpoint_embeddings[str(chunk_id)] = {
                "identity": list(chunk["identity"]),
                "embedding": vector,
                "text": item["text"],
            }

        save_checkpoint(
            checkpoint_path,
            checkpoint_embeddings,
        )

        print(
            f"Checkpoint saved: "
            f"{len(checkpoint_embeddings)}/{len(chunks)}"
        )

    # STEP 5: GENERATE ALL REMAINING EMBEDDINGS

    if pending_chunks:
        pending_input = [
            {
                "id": chunk["id"],
                "repository_chunk_id": chunk["id"],
                "file_path": chunk["file_path"],
                "symbol_name": chunk["symbol_name"],
                "symbol_kind": chunk["symbol_kind"],
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
                "content": chunk["content"],
                "commit_sha": chunk["commit_sha"],
            }
            for chunk in pending_chunks
        ]

        generated = embed_repository_chunks(
            pending_input,
            model=model_name,
            batch_size=settings.embedding_batch_size,
            max_retries=8,
            on_batch_complete=on_batch_complete,
        )

        generated_ids = {
            int(item["repository_chunk_id"])
            for item in generated
        }

        expected_generated_ids = {
            chunk["id"]
            for chunk in pending_chunks
        }

        if generated_ids != expected_generated_ids:
            raise RuntimeError(
                "Generated embedding IDs do not match pending chunks."
            )

    # STEP 6: VALIDATE ALL CHECKPOINT ENTRIES

    if len(checkpoint_embeddings) != len(chunks):
        raise RuntimeError(
            "Checkpoint does not contain all PostgreSQL embeddings."
        )

    target_points = []
    expected = {}

    for chunk in chunks:
        item = checkpoint_embeddings.get(str(chunk["id"]))

        if item is None:
            raise RuntimeError(
                f"Missing embedding for chunk {chunk['id']}"
            )

        if item["identity"] != list(chunk["identity"]):
            raise RuntimeError(
                f"Checkpoint identity mismatch: {chunk['id']}"
            )

        vector = validate_vector(
            item["embedding"],
            chunk["id"],
            vector_dimension,
        )

        point_id = point_id_for_chunk(chunk["id"])

        payload = make_payload(
            chunk,
            item["text"],
        )

        target_points.append(
            PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        )

        expected[point_id] = {
            "chunk_id": chunk["id"],
            "identity": chunk["identity"],
            "model": model_name,
        }

    target_ids = {
        str(point.id)
        for point in target_points
    }

    if len(target_ids) != len(chunks):
        raise RuntimeError("Duplicate target point IDs.")

    if len(target_points) != len(chunks):
        raise RuntimeError("Target point count mismatch.")

    print("\nAll fresh embeddings validated:", len(target_points))

    # STEP 7: BACKUP BEFORE QDRANT MODIFICATION

    backup_path = qdrant_path.parent / (
        qdrant_path.name
        + "_backup_before_full_reembed_"
        + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )

    if backup_path.exists():
        raise RuntimeError(
            "Backup directory already exists."
        )

    print("\nCreating Qdrant backup:", backup_path)

    shutil.copytree(
        qdrant_path,
        backup_path,
    )

    print("Backup completed.")

    # STEP 8: UPSERT ALL FRESH POINTS

    client = QdrantClient(path=str(qdrant_path))

    try:
        client.upsert(
            collection_name=collection_name,
            points=target_points,
            wait=True,
        )

        print("Upserted fresh points:", len(target_points))

        # STEP 9: VERIFY BEFORE DELETION

        verified = verify_target_points(
            client,
            collection_name,
            expected,
            vector_dimension,
        )

        verified_ids = {
            str(record.id)
            for record in verified
        }

        if not target_ids.issubset(verified_ids):
            raise RuntimeError(
                "Target verification failed. "
                "Stale points were NOT deleted."
            )

        print("All target points verified.")

        # STEP 10: DELETE ONLY STALE POINTS

        stale_ids = verified_ids - target_ids

        print("Stale points identified:", len(stale_ids))

        if stale_ids:
            client.delete(
                collection_name=collection_name,
                points_selector=list(stale_ids),
                wait=True,
            )

        # STEP 11: FINAL VERIFICATION

        final_records = scroll_repository(
            client,
            collection_name,
        )

        final_ids = {
            str(record.id)
            for record in final_records
        }

        if final_ids != target_ids:
            raise RuntimeError(
                "Final Qdrant point IDs do not match target IDs."
            )

        verify_target_points(
            client,
            collection_name,
            expected,
            vector_dimension,
        )

        print("\n========== REPAIR SUCCESS ==========")
        print("PostgreSQL chunks:", len(chunks))
        print("Qdrant points:", len(final_records))
        print("Fresh embeddings:", len(target_points))
        print("Embedding model:", model_name)
        print("Vector dimension:", vector_dimension)
        print("Missing mappings: 0")
        print("Stale points: 0")
        print("Backup:", backup_path)
        print("Checkpoint:", checkpoint_path)

    finally:
        client.close()


if __name__ == "__main__":
    main()

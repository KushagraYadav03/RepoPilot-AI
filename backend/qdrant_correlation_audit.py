import uuid
from collections import Counter, defaultdict

from app.db.session import SessionLocal
from app.models.repository_chunk import RepositoryChunk
from app.core.config import settings
from app.services.qdrant_service import get_local_qdrant_client


def expected_point_id(chunk_id):
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"repopilot-point-id:{chunk_id}"
    ))


db = SessionLocal()
client = None

try:
    client = get_local_qdrant_client(str(settings.qdrant_path))
    collection = settings.qdrant_collection

    print("\n========== POSTGRESQL AUDIT ==========")

    chunks = db.query(RepositoryChunk).all()
    print("Total PostgreSQL chunks:", len(chunks))

    pg_ids = {str(c.id) for c in chunks}
    expected_ids = {
        expected_point_id(c.id): c for c in chunks
    }

    print("\n========== QDRANT AUDIT ==========")

    qdrant_points = []
    offset = None

    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        qdrant_points.extend(points)

        if offset is None:
            break

    print("Total Qdrant points:", len(qdrant_points))

    qdrant_ids = [str(p.id) for p in qdrant_points]
    qdrant_id_set = set(qdrant_ids)

    duplicate_ids = [
        point_id for point_id, count in Counter(qdrant_ids).items()
        if count > 1
    ]

    matched = set(expected_ids) & qdrant_id_set
    missing = set(expected_ids) - qdrant_id_set
    orphan = qdrant_id_set - set(expected_ids)

    print("\n========== CORRELATION RESULTS ==========")
    print("Exact matched:", len(matched))
    print("Missing Qdrant points:", len(missing))
    print("Orphan Qdrant points:", len(orphan))
    print("Duplicate Qdrant IDs:", len(duplicate_ids))

    print("\n========== REPOSITORY BREAKDOWN ==========")

    pg_counts = Counter(c.repository_id for c in chunks)
    qdrant_counts = Counter(
        (p.payload or {}).get("repository_id", "MISSING")
        for p in qdrant_points
    )

    for repo_id in sorted(set(pg_counts) | {
        k for k in qdrant_counts if isinstance(k, int)
    }):
        repo_chunks = [
            c for c in chunks if c.repository_id == repo_id
        ]
        repo_matched = sum(
            expected_point_id(c.id) in qdrant_id_set
            for c in repo_chunks
        )
        print(
            f"Repository {repo_id}: "
            f"PostgreSQL={pg_counts[repo_id]}, "
            f"Qdrant={qdrant_counts[repo_id]}, "
            f"Matched={repo_matched}"
        )

    print("\n========== MISSING RECORDS (FIRST 30) ==========")
    for point_id in list(missing)[:30]:
        c = expected_ids[point_id]
        print(
            f"Chunk ID={c.id}, Repo={c.repository_id}, "
            f"File={c.file_path}, Expected UUID={point_id}"
        )

    print("\n========== ORPHAN RECORDS (FIRST 30) ==========")
    qdrant_map = {str(p.id): p for p in qdrant_points}

    for point_id in list(orphan)[:30]:
        p = qdrant_map[point_id]
        payload = p.payload or {}
        print(
            f"UUID={point_id}, "
            f"Repo={payload.get('repository_id')}, "
            f"File={payload.get('file_path')}"
        )

    print("\n========== AUDIT COMPLETED ==========")
    print("READ ONLY: No records were modified or deleted.")

finally:
    db.close()
    if client is not None:
        client.close()


from collections import Counter
from qdrant_client.models import Filter, FieldCondition, MatchValue

from app.core.config import settings
from app.services.qdrant_service import get_local_qdrant_client

client = None

try:
    client = get_local_qdrant_client(str(settings.qdrant_path))
    collection = settings.qdrant_collection

    print("\n1. COLLECTION INFO")
    info = client.get_collection(collection)
    print("Collection:", collection)
    print("Points:", info.points_count)
    print("Vector config:", info.config.params.vectors)

    print("\n2. REPOSITORY 1 COUNT")
    result = client.count(
        collection_name=collection,
        count_filter=Filter(
            must=[
                FieldCondition(
                    key="repository_id",
                    match=MatchValue(value=1)
                )
            ]
        ),
        exact=True
    )
    print("Repository 1 points:", result.count)

    print("\n3. ALL POINTS BY REPOSITORY")
    points, offset = client.scroll(
        collection_name=collection,
        limit=100,
        with_payload=True,
        with_vectors=False
    )

    counts = Counter(
        str((p.payload or {}).get("repository_id", "MISSING"))
        for p in points
    )

    print("Fetched:", len(points))
    print("Breakdown:", dict(counts))

    print("\n4. FIRST FIVE PAYLOADS")
    for point in points[:5]:
        payload = point.payload or {}
        print("\nID:", point.id)
        print("Repository:", payload.get("repository_id"))
        print("File:", payload.get("file_path"))
        print("Content exists:", bool(payload.get("content")))
        print("Keys:", list(payload.keys()))

    print("\n5. MISSING REPOSITORY IDS")
    missing = [
        p.id for p in points
        if "repository_id" not in (p.payload or {})
    ]
    print("Missing:", len(missing))

except Exception as exc:
    print("DIAGNOSTIC ERROR:", repr(exc))

finally:
    if client is not None:
        client.close()

print("\nDIAGNOSTIC COMPLETED")

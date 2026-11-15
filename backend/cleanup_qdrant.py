import sys

from app.core.config import settings
from app.services.qdrant_service import get_local_qdrant_client
from app.utils.file_filters import should_exclude_file


def main() -> None:
    client = get_local_qdrant_client(settings.qdrant_path)

    if not client.collection_exists(settings.qdrant_collection):
        print("Collection does not exist. Nothing to clean.")
        return

    ids, paths = [], set()
    offset = None

    while True:
        records, offset = client.scroll(
            settings.qdrant_collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            file_path = (record.payload or {}).get("file_path", "")
            if should_exclude_file(file_path):
                ids.append(record.id)
                paths.add(file_path)
        if offset is None:
            break

    print(f"{len(ids)} points in {len(paths)} files would be removed:")
    for path in sorted(paths):
        print("  ", path)

    if "--delete" not in sys.argv:
        print("\nDry run only. Re-run with --delete to remove them.")
        return

    if not ids:
        print("Nothing to delete.")
        return

    client.delete(
        settings.qdrant_collection,
        points_selector=ids,
        wait=True,
    )
    print("Deleted.")


if __name__ == "__main__":
    main()

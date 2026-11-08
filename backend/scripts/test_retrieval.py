from app.services.retrieval_service import (
    retrieve_repository_chunks,
)


REPOSITORY_ID = 1


queries = [
    "Where is JWT authentication implemented?",
    "Find database connection and SQLAlchemy sessions",
    "Where are API endpoints defined?",
    "Find repository ingestion logic",
]


for query in queries:

    print("\n" + "=" * 60)
    print("QUERY:", query)
    print("=" * 60)

    try:

        results = retrieve_repository_chunks(
            repository_id=REPOSITORY_ID,
            query=query,
            limit=5,
        )

        if not results:
            print("No relevant chunks found")
            continue

        for index, result in enumerate(results, 1):

            print(f"\nResult {index}")

            print("File:", result["file_path"])
            print("Symbol:", result["symbol_name"])

            print(
                "Lines:",
                result["start_line"],
                "-",
                result["end_line"],
            )

            print("Score:", result["score"])

            print("Content:")
            print(result["content"][:500])

    except Exception as exc:

        print("Retrieval failed:", str(exc))
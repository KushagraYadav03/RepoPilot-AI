
import sys
from pathlib import Path

# Add backend directory to Python import path
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.services.retrieval_service import (
    retrieve_repository_chunks,
)


REPOSITORY_ID = 1
TOP_K = 20


evaluation_cases = [
    {
        "question": "Where is JWT authentication implemented?",
        "expected_files": [
            "jwt.py",
            "dependencies.py",
            "security.py",
        ],
    },
    {
        "question": "Find database connection and SQLAlchemy sessions",
        "expected_files": [
            "session.py",
            "config.py",
            "base.py",
        ],
    },
    {
        "question": "Where are API endpoints defined?",
        "expected_files": [
            "routes/auth.py",
            "routes/repositories.py",
            "routes/chat.py",
            "routes/retrieval.py",
        ],
    },
    {
        "question": "Explain how repository ingestion works",
        "expected_files": [
            "ingestion_service.py",
            "git_service.py",
            "file_processor.py",
            "chunking_service.py",
        ],
    },
    {
        "question": "How does RAG retrieve relevant code chunks?",
        "expected_files": [
            "retrieval_service.py",
            "embedding_service.py",
            "qdrant_service.py",
            "rag_service.py",
        ],
    },
]


results_summary = []


print("\n" + "=" * 70)
print("REPOPILOT AI - RETRIEVAL EVALUATION")
print("=" * 70)


for case in evaluation_cases:

    question = case["question"]
    expected_files = case["expected_files"]

    print("\n" + "=" * 70)
    print("QUESTION:", question)
    print("=" * 70)

    print("Expected files:", expected_files)

    try:

        results = retrieve_repository_chunks(
            repository_id=REPOSITORY_ID,
            query=question,
            limit=TOP_K,
        )

        if not results:

            print("\nNo relevant chunks found")
            print("STATUS: FAIL")

            results_summary.append({
                "question": question,
                "status": "FAIL",
                "matched_files": [],
            })

            continue

        matched_files = []

        for index, result in enumerate(results, 1):

            file_path = result["file_path"]
            normalized_path = file_path.replace("\\", "/").lower()

            print(f"\nResult {index}")
            print("File:", file_path)
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

            for expected_file in expected_files:

                if normalized_path.endswith(
                    expected_file.lower()
                ):

                    if expected_file not in matched_files:
                        matched_files.append(expected_file)

        print("\nMatched expected files:", matched_files)

        if matched_files:
            status = "PASS"
        else:
            status = "FAIL"

        print("STATUS:", status)

        results_summary.append({
            "question": question,
            "status": status,
            "matched_files": matched_files,
        })

    except Exception as exc:

        print("\nRetrieval failed:", str(exc))
        print("STATUS: ERROR")

        results_summary.append({
            "question": question,
            "status": "ERROR",
            "matched_files": [],
        })


print("\n" + "=" * 70)
print("FINAL EVALUATION SUMMARY")
print("=" * 70)


for index, item in enumerate(results_summary, 1):

    print(f"\nTest {index}")
    print("Question:", item["question"])
    print("Matched files:", item["matched_files"])
    print("Status:", item["status"])


total = len(results_summary)

passed = sum(
    1 for item in results_summary
    if item["status"] == "PASS"
)

failed = sum(
    1 for item in results_summary
    if item["status"] == "FAIL"
)

errors = sum(
    1 for item in results_summary
    if item["status"] == "ERROR"
)


print("\n" + "=" * 70)
print("TOTAL TESTS:", total)
print("PASSED:", passed)
print("FAILED:", failed)
print("ERRORS:", errors)

if total:
    print(
        "RETRIEVAL PASS RATE:",
        f"{(passed / total) * 100:.2f}%"
    )

print("=" * 70)


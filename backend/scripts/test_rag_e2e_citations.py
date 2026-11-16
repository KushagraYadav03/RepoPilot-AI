import asyncio
import re
import sys
from pathlib import Path

# Add backend directory to Python import path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.rag_service import answer_repository_question

TEST_CASES = [
    {
        "name": "Authentication & Password Hashing",
        "query": "Where is user authentication implemented, and how are passwords verified?",
        "expected_symbols": ["login", "verify_password", "create_access_token"],
        "expect_has_sources": True,
    },
    {
        "name": "Code Chunking & AST Parsing",
        "query": "How are code symbols parsed and chunked from source files?",
        "expected_symbols": ["chunk_code", "parse_code_symbols", "_chunk_python_code"],
        "expect_has_sources": True,
    },
    {
        "name": "Qdrant Vector Storage",
        "query": "Where are repository embeddings stored into Qdrant?",
        "expected_symbols": ["store_repository_embeddings", "upsert_points"],
        "expect_has_sources": True,
    },
    {
        "name": "Hallucination Resistance (Non-Existent Feature)",
        "query": "How is Stripe subscription billing and credit card processing implemented in this repository?",
        "expected_symbols": [],
        "expect_has_sources": False,
    },
]


async def run_e2e_evaluation():
    print("=" * 80)
    print("REPOPILOT AI - FULL END-TO-END RAG & CITATION ACCURACY EVALUATION")
    print("=" * 80)

    total_tests = len(TEST_CASES)
    passed_tests = 0
    failures = []

    for index, case in enumerate(TEST_CASES, start=1):
        print(f"\n[{index}/{total_tests}] TEST: {case['name']}")
        print(f"Query: \"{case['query']}\"")
        print("-" * 80)

        result = await answer_repository_question(
            repository_id=1,
            query=case["query"],
            limit=5,
        )

        answer = result["answer"]
        provider = result["provider"]
        model = result["model"]
        sources = result["sources"]

        print(f"Provider: {provider} | Model: {model}")
        print(f"Sources returned: {len(sources)}")
        for s in sources:
            print(
                f"  [{s['source_id']}] {s['file_path']} :: {s['symbol_name']} "
                f"(lines {s['start_line']}-{s['end_line']}) score={s['score']:.4f}"
            )

        print("\nGenerated Answer:")
        print(answer)
        print("-" * 80)

        test_passed = True
        case_errors = []

        if not case["expect_has_sources"]:
            # For non-existent features, answer should explicitly state no relevant code or insufficient context
            lower_answer = answer.lower()
            not_found_phrases = [
                "could not find",
                "not find relevant code",
                "insufficient",
                "no relevant",
                "not implement",
                "does not contain",
                "does not appear",
                "no evidence",
            ]
            if not any(phrase in lower_answer for phrase in not_found_phrases):
                case_errors.append("Answer did not acknowledge absence of feature; risk of hallucination.")
                test_passed = False
            else:
                print("CHECK PASS: Correctly refused/acknowledged absence of non-existent feature.")
        else:
            # 1. Check citations syntax in answer
            citations = re.findall(r"\[(S\d+)\]", answer)
            if not citations:
                case_errors.append("Answer contains no citation tags [S1], [S2] etc.")
                test_passed = False
            else:
                print(f"CHECK PASS: Found citations: {set(citations)}")

            # 2. Check for phantom citations (citations cited but not in sources)
            available_source_ids = {s["source_id"] for s in sources}
            phantom_citations = set(citations) - available_source_ids
            if phantom_citations:
                case_errors.append(f"Phantom citations found in answer: {phantom_citations}")
                test_passed = False
            else:
                print("CHECK PASS: All citations match returned source IDs.")

            # 3. Check for relevance of sources
            retrieved_symbols = [s["symbol_name"] for s in sources]
            matched_symbols = [sym for sym in case["expected_symbols"] if sym in retrieved_symbols]
            if not matched_symbols:
                case_errors.append(
                    f"None of expected symbols {case['expected_symbols']} found in retrieved: {retrieved_symbols}"
                )
                test_passed = False
            else:
                print(f"CHECK PASS: Retrieved relevant symbol(s): {matched_symbols}")

            # 4. Check that source line ranges and file paths are valid
            for s in sources:
                if not s["file_path"] or not isinstance(s["start_line"], int) or not isinstance(s["end_line"], int):
                    case_errors.append(f"Invalid metadata in source: {s}")
                    test_passed = False
                elif s["start_line"] > s["end_line"]:
                    case_errors.append(f"Invalid line range in source: {s['start_line']} > {s['end_line']}")
                    test_passed = False

        if test_passed:
            print(f"RESULT: PASS ({case['name']})")
            passed_tests += 1
        else:
            print(f"RESULT: FAIL ({case['name']}) - Errors: {case_errors}")
            failures.append((case["name"], case_errors))

    print("\n" + "=" * 80)
    print("FINAL EVALUATION REPORT")
    print(f"Passed: {passed_tests}/{total_tests} ({(passed_tests/total_tests)*100:.1f}%)")
    if failures:
        print("Failures:")
        for name, errs in failures:
            print(f" - {name}: {errs}")
    else:
        print("ALL END-TO-END RAG RETRIEVAL & CITATION CHECKS PASSED PERFECTLY!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_e2e_evaluation())

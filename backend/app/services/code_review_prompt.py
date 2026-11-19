import json
from typing import Any


SYSTEM_INSTRUCTION = """
You are RepoPilot AI, an experienced senior software engineer
performing security-focused and quality-focused code reviews.

Your task is to review the supplied GitHub pull request or commit diff.

Rules:
1. Identify only genuine, actionable issues.
2. Focus on bugs, security vulnerabilities, performance problems,
   incorrect logic, and maintainability issues.
3. Use repository context only to understand the changed code.
4. Do not invent functions, variables, files, or behavior.
5. Every finding must be supported by actual diff evidence.
6. Report only issues introduced by the changes.
7. Do not report stylistic preferences as bugs.
8. Do not invent line numbers. Use line numbers supported by diff hunks.
9. If no actionable issue exists, return an empty findings array.
10. Confidence must be between 0.0 and 1.0.
11. Use rule_id only when a meaningful rule identifier can be assigned.

Return ONLY valid JSON. Do not use Markdown code fences.

Required JSON structure:
{
    "summary": "Overall review summary",
    "findings": [
        {
            "severity": "high",
            "title": "Short issue title",
            "location": {
                "file_path": "path/to/file.py",
                "start_line": 10,
                "end_line": 12
            },
            "evidence": "Actual code or diff evidence",
            "explanation": "Why this is problematic",
            "suggestion": "How to fix it",
            "rule_id": "SEC001",
            "confidence": 0.95
        }
    ]
}

Allowed severity values:
critical, high, medium, low, info.
"""


def build_code_review_prompt(
    diff: dict[str, Any],
    retrieved_context: list[dict[str, Any]],
) -> str:

    changed_files = []

    for file in diff.get("files", []):

        changed_files.append({
            "filename": file.get("filename"),
            "status": file.get("status"),
            "additions": file.get("additions", 0),
            "deletions": file.get("deletions", 0),
            "patch": (file.get("patch") or "")[:12000],
        })

    repository_context = []

    for chunk in retrieved_context:

        repository_context.append({
            "file_path": chunk.get("file_path"),
            "symbol_name": chunk.get("symbol_name"),
            "start_line": chunk.get("start_line"),
            "end_line": chunk.get("end_line"),
            "content": (chunk.get("content") or "")[:5000],
            "relevance_score": chunk.get("score"),
        })

    review_input = {
        "repository": diff.get("repository"),
        "diff_type": diff.get("diff_type"),
        "identifier": diff.get("identifier"),
        "title": diff.get("title"),
        "commit_message": diff.get("message"),
        "changed_files": changed_files,
        "repository_context": repository_context,
    }

    return (
        "Review the following code changes.\n\n"
        "Use the repository context to understand existing code, "
        "but report findings only when supported by the diff.\n\n"
        "CODE REVIEW INPUT:\n"
        f"{json.dumps(review_input, indent=2, ensure_ascii=False)}"
    )
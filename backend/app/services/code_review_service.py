
import json
import logging
from typing import Any

from app.services.llm_service import LLMService

from app.services.retrieval_service import (
    retrieve_repository_chunks,
)

from app.services.context_enrichment import (
    enrich_review_context,
)

from app.services.code_review_prompt import (
    SYSTEM_INSTRUCTION,
    build_code_review_prompt,
)

from app.services.static_analysis_service import (
    StaticAnalysisService,
)

from app.schemas.code_review import (
    CodeReviewResponse,
    ReviewFinding,
)


logger = logging.getLogger(__name__)


class CodeReviewService:

    def __init__(self):
        self.llm_service = LLMService()
        self.static_analysis_service = StaticAnalysisService()

    async def review_code_changes(
        self,
        repository_id: int,
        diff: dict[str, Any],
    ) -> CodeReviewResponse:

        if repository_id <= 0:
            raise ValueError(
                "Repository ID must be greater than zero"
            )

        if not isinstance(diff, dict):
            raise ValueError("Invalid diff data")

        required_fields = (
            "repository",
            "diff_type",
            "identifier",
        )

        for field in required_fields:

            if not diff.get(field):
                raise ValueError(
                    f"Diff field '{field}' is required"
                )

        files = diff.get("files")

        if not isinstance(files, list) or not files:
            raise ValueError(
                "No changed files available for code review"
            )

        # ---------------------------------------------
        # STEP 1: BUILD RETRIEVAL QUERY
        # ---------------------------------------------

        query = self._build_retrieval_query(diff)

        # ---------------------------------------------
        # STEP 2: ENRICH REPOSITORY CONTEXT
        # ---------------------------------------------

        retrieved_context = enrich_review_context(
            repository_id=repository_id,
            diff=diff,
            base_query=query,
            retrieve_chunks=retrieve_repository_chunks,
            semantic_limit=10,
            structural_limit=20,
        )

        logger.info(
            "Generated enriched context for repository %s: %s chunks",
            repository_id,
            len(retrieved_context),
        )

        # ---------------------------------------------
        # STEP 3: BUILD REVIEW PROMPT
        # ---------------------------------------------

        prompt = build_code_review_prompt(
            diff=diff,
            retrieved_context=retrieved_context,
        )

        # ---------------------------------------------
        # STEP 4: GENERATE LLM REVIEW
        # ---------------------------------------------

        llm_response = await self.llm_service.generate(
            prompt=prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.1,
            max_output_tokens=8192,
        )

        # ---------------------------------------------
        # STEP 5: PARSE LLM RESPONSE
        # ---------------------------------------------

        review_data = self._parse_llm_response(
            llm_response.text
        )

        review_data["repository"] = diff["repository"]
        review_data["diff_type"] = diff["diff_type"]
        review_data["identifier"] = diff["identifier"]
        review_data["title"] = diff.get("title")

        try:

            ai_review = CodeReviewResponse.model_validate(
                review_data
            )

        except Exception as exc:

            logger.exception(
                "LLM returned an invalid code review response"
            )

            raise ValueError(
                "Unable to validate the generated code review"
            ) from exc

        # ---------------------------------------------
        # STEP 6: RUN STATIC ANALYSIS
        # ---------------------------------------------

        static_findings = await self._run_static_analysis(
            diff=diff,
            files=files,
        )

        logger.info(
            "Static analysis generated %s findings",
            len(static_findings),
        )

        # ---------------------------------------------
        # STEP 7: MERGE AI + STATIC FINDINGS
        # ---------------------------------------------

        merged_findings = self._merge_findings(
            ai_findings=ai_review.findings,
            static_findings=static_findings,
        )

        # model_copy keeps the same response structure.
        # Statistics are computed from the merged findings.
        final_review = ai_review.model_copy(
            update={
                "findings": merged_findings,
            }
        )

        logger.info(
            (
                "Code review completed for repository %s. "
                "AI findings: %s, static findings: %s, "
                "total findings: %s"
            ),
            repository_id,
            len(ai_review.findings),
            len(static_findings),
            len(final_review.findings),
        )

        return final_review

    # =================================================
    # STATIC ANALYSIS
    # =================================================

    async def _run_static_analysis(
        self,
        diff: dict[str, Any],
        files: list[dict[str, Any]],
    ) -> list[ReviewFinding]:

        repository = diff.get("repository", "")

        if not isinstance(repository, str):
            return []

        parts = repository.split("/", 1)

        if len(parts) != 2:
            logger.warning(
                "Invalid repository name for static analysis: %s",
                repository,
            )
            return []

        owner, repo = parts

        # PR analysis must use the PR head commit.
        # Commit analysis can use its commit SHA.
        ref = diff.get("head_sha")

        if not ref and diff.get("diff_type") == "commit":
            ref = diff.get("identifier")

        if not ref:
            logger.warning(
                "No source commit SHA available. "
                "Skipping static analysis."
            )
            return []

        try:

            return await self.static_analysis_service.analyze_changed_files(
                owner=owner,
                repo=repo,
                ref=ref,
                files=files,
            )

        except Exception:

            # Static analysis should not break the existing
            # AI review pipeline if an analyzer fails.
            logger.exception(
                "Static analysis failed for %s",
                repository,
            )

            return []

    # =================================================
    # MERGE AND DEDUPLICATE FINDINGS
    # =================================================

    @staticmethod
    def _merge_findings(
        ai_findings: list[ReviewFinding],
        static_findings: list[ReviewFinding],
    ) -> list[ReviewFinding]:

        merged: list[ReviewFinding] = []
        seen = set()

        for finding in [
            *ai_findings,
            *static_findings,
        ]:

            if not isinstance(finding, ReviewFinding):
                finding = ReviewFinding.model_validate(
                    finding
                )

            location = finding.location

            # Rule-based findings use rule_id for identity.
            # AI findings without rule_id use their title.
            identity = (
                location.file_path,
                location.start_line,
                location.end_line,
                finding.rule_id or finding.title.strip().lower(),
            )

            if identity in seen:
                continue

            seen.add(identity)
            merged.append(finding)

        return merged

    # =================================================
    # BUILD RETRIEVAL QUERY
    # =================================================

    @staticmethod
    def _build_retrieval_query(
        diff: dict[str, Any],
    ) -> str:

        query_parts = []

        for file in diff.get("files", []):

            if not isinstance(file, dict):
                continue

            filename = file.get("filename", "")
            patch = file.get("patch") or ""

            query_parts.append(
                f"File: {filename}\n{patch[:3000]}"
            )

        query = "\n\n".join(query_parts)

        return (
            "Understand the existing implementation and dependencies "
            "related to these code changes:\n"
            f"{query[:12000]}"
        )

    # =================================================
    # PARSE LLM RESPONSE
    # =================================================

    @staticmethod
    def _parse_llm_response(
        response_text: str,
    ) -> dict[str, Any]:

        if not response_text or not response_text.strip():

            raise ValueError(
                "LLM returned an empty code review response"
            )

        cleaned_response = response_text.strip()

        if cleaned_response.startswith("```"):

            lines = cleaned_response.splitlines()

            if lines[-1].strip().startswith("```"):
                lines = lines[:-1]

            lines = lines[1:]

            cleaned_response = "\n".join(lines).strip()

        try:

            parsed = json.loads(cleaned_response)

        except json.JSONDecodeError as exc:

            logger.error(
                "Unable to parse LLM code review JSON"
            )

            raise ValueError(
                "LLM returned invalid JSON for code review"
            ) from exc

        if not isinstance(parsed, dict):

            raise ValueError(
                "LLM response must be a JSON object"
            )

        return parsed

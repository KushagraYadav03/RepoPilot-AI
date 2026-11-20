
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

from app.schemas.code_review import (
    CodeReviewResponse,
)


logger = logging.getLogger(__name__)


class CodeReviewService:

    def __init__(self):
        self.llm_service = LLMService()

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

            return CodeReviewResponse.model_validate(
                review_data
            )

        except Exception as exc:

            logger.exception(
                "LLM returned an invalid code review response"
            )

            raise ValueError(
                "Unable to validate the generated code review"
            ) from exc

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


import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_db,
    get_current_user_id,
)

from app.schemas.patch_generation import (
    GeneratePatchRequest,
    GeneratedPatchResponse,
)

from app.schemas.patch_validation import (
    ValidatePatchRequest,
    PatchValidationResponse,
)

from app.services.patch_generation_service import (
    PatchGenerationService,
)

from app.services.patch_validation_service import (
    PatchValidationService,
)

from app.repositories.repository_repository import (
    get_repository_by_id,
)

from app.repositories.code_review_repository import (
    create_code_review,
    get_code_review_by_id,
)

from app.services.git_service import (
    extract_github_repository,
    fetch_github_pull_request_diff,
    fetch_github_commit_diff,
    fetch_github_file_content,
)

from app.services.code_review_service import CodeReviewService

from app.schemas.review import (
    CreateCodeReviewRequest,
    SavedCodeReviewResponse,
)

from app.schemas.code_review import (
    ReviewDiffType,
    CodeReviewResponse,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/reviews",
    tags=["Code Reviews"],
)


code_review_service = CodeReviewService()
patch_generation_service = PatchGenerationService()
patch_validation_service = PatchValidationService()


# =========================================================
# WEEK 5 - DAY 3: CREATE CODE REVIEW
# =========================================================

@router.post(
    "",
    response_model=SavedCodeReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    request: CreateCodeReviewRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    repository = get_repository_by_id(
        db=db,
        repository_id=request.repository_id,
        owner_id=current_user_id,
    )

    if repository is None:
        raise HTTPException(
            status_code=404,
            detail="Repository not found",
        )

    try:
        owner, repo = extract_github_repository(
            repository.github_url
        )

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    try:

        if request.diff_type == ReviewDiffType.PULL_REQUEST:

            try:
                pull_number = int(request.identifier)

            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Pull request identifier must be a number",
                ) from exc

            if pull_number <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Pull request number must be positive",
                )

            diff = await fetch_github_pull_request_diff(
                owner=owner,
                repo=repo,
                pull_number=pull_number,
            )

        elif request.diff_type == ReviewDiffType.COMMIT:

            diff = await fetch_github_commit_diff(
                owner=owner,
                repo=repo,
                commit_sha=request.identifier,
            )

        else:
            raise HTTPException(
                status_code=422,
                detail="Unsupported diff type",
            )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Unable to fetch GitHub diff")

        raise HTTPException(
            status_code=502,
            detail="Unable to fetch changes from GitHub",
        ) from exc

    try:

        generated_review = (
            await code_review_service.review_code_changes(
                repository_id=repository.id,
                diff=diff,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("Code review generation failed")

        raise HTTPException(
            status_code=502,
            detail="Unable to generate code review",
        ) from exc

    review_data = generated_review.model_dump(
        mode="json"
    )

    try:

        saved_review = create_code_review(
            db=db,
            user_id=current_user_id,
            repository_id=repository.id,
            diff_type=request.diff_type.value,
            identifier=request.identifier,
            title=generated_review.title,
            review_data=review_data,
        )

    except Exception as exc:
        logger.exception("Unable to save code review")

        raise HTTPException(
            status_code=500,
            detail="Unable to save generated code review",
        ) from exc

    return SavedCodeReviewResponse(
        id=saved_review.id,
        repository_id=saved_review.repository_id,
        diff_type=saved_review.diff_type,
        identifier=saved_review.identifier,
        created_at=saved_review.created_at,
        review=generated_review,
    )


# =========================================================
# GET SAVED CODE REVIEW
# =========================================================

@router.get(
    "/{review_id}",
    response_model=SavedCodeReviewResponse,
)
async def get_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    if review_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="Review ID must be positive",
        )

    saved_review = get_code_review_by_id(
        db=db,
        review_id=review_id,
        user_id=current_user_id,
    )

    if saved_review is None:
        raise HTTPException(
            status_code=404,
            detail="Code review not found",
        )

    try:

        review = CodeReviewResponse.model_validate(
            saved_review.review_data
        )

    except Exception as exc:
        logger.exception(
            "Stored code review data is invalid"
        )

        raise HTTPException(
            status_code=500,
            detail="Stored code review data is invalid",
        ) from exc

    return SavedCodeReviewResponse(
        id=saved_review.id,
        repository_id=saved_review.repository_id,
        diff_type=saved_review.diff_type,
        identifier=saved_review.identifier,
        created_at=saved_review.created_at,
        review=review,
    )


# =========================================================
# WEEK 6 - DAY 5: PATCH GENERATION
# =========================================================

@router.post(
    "/{review_id}/patches/generate",
    response_model=GeneratedPatchResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_review_patch(
    review_id: int,
    request: GeneratePatchRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    if review_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="Review ID must be positive",
        )

    saved_review = get_code_review_by_id(
        db=db,
        review_id=review_id,
        user_id=current_user_id,
    )

    if saved_review is None:
        raise HTTPException(
            status_code=404,
            detail="Code review not found",
        )

    repository = get_repository_by_id(
        db=db,
        repository_id=saved_review.repository_id,
        owner_id=current_user_id,
    )

    if repository is None:
        raise HTTPException(
            status_code=404,
            detail="Repository not found",
        )

    try:
        owner, repo = extract_github_repository(
            repository.github_url
        )

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    try:

        if saved_review.diff_type == ReviewDiffType.PULL_REQUEST.value:

            pull_number = int(saved_review.identifier)

            if pull_number <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid stored pull request number",
                )

            diff_data = await fetch_github_pull_request_diff(
                owner=owner,
                repo=repo,
                pull_number=pull_number,
            )

        elif saved_review.diff_type == ReviewDiffType.COMMIT.value:

            diff_data = await fetch_github_commit_diff(
                owner=owner,
                repo=repo,
                commit_sha=saved_review.identifier,
            )

        else:
            raise HTTPException(
                status_code=422,
                detail="Unsupported stored review diff type",
            )

    except HTTPException:
        raise

    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid stored review identifier",
        ) from exc

    except Exception as exc:
        logger.exception(
            "Unable to fetch GitHub diff for patch generation"
        )

        raise HTTPException(
            status_code=502,
            detail="Unable to fetch GitHub changes",
        ) from exc

    try:

        patch_result = await patch_generation_service.generate_patch(
            owner=owner,
            repo=repo,
            review_data=saved_review.review_data,
            diff_data=diff_data,
            finding_index=request.finding_index,
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Patch generation failed for review ID %s",
            review_id,
        )

        raise HTTPException(
            status_code=502,
            detail="Unable to generate code patch",
        ) from exc

    return GeneratedPatchResponse(
        review_id=saved_review.id,
        finding_index=patch_result["finding_index"],
        file_path=patch_result["file_path"],
        finding_title=patch_result["finding_title"],
        patch=patch_result["patch"],
        message=patch_result["message"],
    )


# =========================================================
# WEEK 6 - DAY 6: PATCH VALIDATION AND SANDBOX EXECUTION
# =========================================================

@router.post(
    "/{review_id}/patches/validate",
    response_model=PatchValidationResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_review_patch(
    review_id: int,
    request: ValidatePatchRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    if review_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="Review ID must be positive",
        )

    # -----------------------------------------------------
    # 1. Fetch saved review with user ownership validation
    # -----------------------------------------------------

    saved_review = get_code_review_by_id(
        db=db,
        review_id=review_id,
        user_id=current_user_id,
    )

    if saved_review is None:
        raise HTTPException(
            status_code=404,
            detail="Code review not found",
        )

    # -----------------------------------------------------
    # 2. Verify repository ownership
    # -----------------------------------------------------

    repository = get_repository_by_id(
        db=db,
        repository_id=saved_review.repository_id,
        owner_id=current_user_id,
    )

    if repository is None:
        raise HTTPException(
            status_code=404,
            detail="Repository not found",
        )

    # -----------------------------------------------------
    # 3. Extract GitHub repository details
    # -----------------------------------------------------

    try:
        owner, repo = extract_github_repository(
            repository.github_url
        )

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    # -----------------------------------------------------
    # 4. Fetch the latest GitHub diff
    # -----------------------------------------------------

    try:

        if saved_review.diff_type == ReviewDiffType.PULL_REQUEST.value:

            try:
                pull_number = int(saved_review.identifier)

            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid stored pull request number",
                ) from exc

            if pull_number <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid stored pull request number",
                )

            diff_data = await fetch_github_pull_request_diff(
                owner=owner,
                repo=repo,
                pull_number=pull_number,
            )

        elif saved_review.diff_type == ReviewDiffType.COMMIT.value:

            diff_data = await fetch_github_commit_diff(
                owner=owner,
                repo=repo,
                commit_sha=saved_review.identifier,
            )

        else:
            raise HTTPException(
                status_code=422,
                detail="Unsupported stored review diff type",
            )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Unable to fetch GitHub diff for patch validation"
        )

        raise HTTPException(
            status_code=502,
            detail="Unable to fetch latest GitHub changes",
        ) from exc

    # -----------------------------------------------------
    # 5. Select finding and verify changed file
    # -----------------------------------------------------

    finding = patch_generation_service.select_finding(
        review_data=saved_review.review_data,
        finding_index=request.finding_index,
    )

    file_path = patch_generation_service.validate_changed_file(
        finding=finding,
        diff_data=diff_data,
    )

    # -----------------------------------------------------
    # 6. Get latest source using GitHub head SHA
    # -----------------------------------------------------

    head_sha = diff_data.get("head_sha")

    if not isinstance(head_sha, str) or not head_sha.strip():
        raise HTTPException(
            status_code=422,
            detail="GitHub diff does not contain a valid head SHA",
        )

    try:
        original_source = await fetch_github_file_content(
            owner=owner,
            repo=repo,
            file_path=file_path,
            ref=head_sha,
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Unable to fetch original GitHub source for validation"
        )

        raise HTTPException(
            status_code=502,
            detail="Unable to fetch original source from GitHub",
        ) from exc

    if original_source is None:
        raise HTTPException(
            status_code=404,
            detail="Unable to fetch the original source file from GitHub",
        )

    if not isinstance(original_source, str):
        raise HTTPException(
            status_code=502,
            detail="GitHub returned invalid source content",
        )

    # -----------------------------------------------------
    # 7. Apply patch and execute patched source in sandbox
    # -----------------------------------------------------

    try:

        validation_result = (
            await patch_validation_service.validate_and_execute(
                file_path=file_path,
                original_source=original_source,
                patch=request.patch,
                language=request.language,
                test_code=request.test_code,
                test_filename=request.test_filename,
            )
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Patch validation failed for review ID %s",
            review_id,
        )

        raise HTTPException(
            status_code=502,
            detail="Unable to validate and execute the generated patch",
        ) from exc

    # -----------------------------------------------------
    # 8. Return validation result
    # -----------------------------------------------------

    return PatchValidationResponse(
        review_id=saved_review.id,
        finding_index=request.finding_index,
        file_path=file_path,
        patch_applied=validation_result["patch_applied"],
        source_matches=validation_result["source_matches"],
        sandbox=validation_result["sandbox"],
        message=validation_result["message"],
    )

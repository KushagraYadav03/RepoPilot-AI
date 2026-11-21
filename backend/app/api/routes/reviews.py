import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_db,
    get_current_user_id,
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

    # ---------------------------------------------
    # STEP 1: CHECK REPOSITORY OWNERSHIP
    # ---------------------------------------------

    repository = get_repository_by_id(
        db=db,
        repository_id=request.repository_id,
        owner_id=current_user_id,
    )

    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    # ---------------------------------------------
    # STEP 2: EXTRACT GITHUB OWNER AND REPO
    # ---------------------------------------------

    try:
        owner, repo = extract_github_repository(
            repository.github_url
        )

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # ---------------------------------------------
    # STEP 3: FETCH GITHUB DIFF
    # ---------------------------------------------

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

    # ---------------------------------------------
    # STEP 4: GENERATE CODE REVIEW
    # ---------------------------------------------

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

    # ---------------------------------------------
    # STEP 5: SAVE REVIEW IN POSTGRESQL
    # ---------------------------------------------

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

    # ---------------------------------------------
    # STEP 6: RETURN SAVED REVIEW
    # ---------------------------------------------

    return SavedCodeReviewResponse(
        id=saved_review.id,
        repository_id=saved_review.repository_id,
        diff_type=saved_review.diff_type,
        identifier=saved_review.identifier,
        created_at=saved_review.created_at,
        review=generated_review,
    )


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

    # ---------------------------------------------
    # STEP 1: FETCH REVIEW FOR LOGGED-IN USER
    # ---------------------------------------------

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

    # ---------------------------------------------
    # STEP 2: RETURN STORED REVIEW
    # ---------------------------------------------

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
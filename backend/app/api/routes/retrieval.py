
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_db,
    get_current_user_id,
    resolve_user_id,
)

from app.models.repository import Repository

from app.schemas.retrieval import (
    RetrievalRequest,
    RetrievedChunkResponse,
)

from app.services.retrieval_service import (
    retrieve_repository_chunks,
)


router = APIRouter(
    prefix="/repositories",
    tags=["Repository Retrieval"],
)


@router.post(
    "/{repository_id}/search",
    response_model=list[RetrievedChunkResponse],
)
def search_repository(
    repository_id: int,
    request: RetrievalRequest,
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user_id),
):
    user_id = resolve_user_id(current_user)

    repository = db.get(
        Repository,
        repository_id,
    )

    if repository is None or repository.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    try:
        results = retrieve_repository_chunks(
            repository_id=repository_id,
            query=request.query,
            limit=request.limit,
            score_threshold=request.score_threshold,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return results


from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_db,
    get_current_user_id,
    resolve_user_id,
)

from app.models.repository import Repository

from app.schemas.chat import (
    RepositoryChatRequest,
    RepositoryChatResponse,
)

from app.services.rag_service import (
    answer_repository_question,
)


router = APIRouter(
    prefix="/repositories",
    tags=["Repository Chat"],
)


@router.post(
    "/{repository_id}/chat",
    response_model=RepositoryChatResponse,
)
async def chat_with_repository(
    repository_id: int,
    request: RepositoryChatRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):

    user_id = resolve_user_id(
        db,
        current_user_id,
    )

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

        result = await answer_repository_question(
            repository_id=repository_id,
            query=request.query,
            limit=request.limit,
            score_threshold=request.score_threshold,
        )

        return result

    except ValueError as exc:

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    except RuntimeError as exc:

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )

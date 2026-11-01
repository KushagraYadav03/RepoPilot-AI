
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.user import User
from app.schemas.repository import RepositoryCreate, RepositoryResponse
from app.repositories.repository_repository import (
    create_repository,
    get_user_repositories,
    get_repository_by_id,
    delete_repository,
)
from app.core.dependencies import get_current_user_id 


router = APIRouter(
    prefix="/repositories",
    tags=["Repositories"]
)


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED
)
def add_repository(
    data: RepositoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_id)
):
    return create_repository(
        db,
        data.name,
        str(data.github_url),
        current_user.id
    )


@router.get("", response_model=list[RepositoryResponse])
def list_repositories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_id)
):
    return get_user_repositories(db, current_user.id)


@router.get(
    "/{repository_id}",
    response_model=RepositoryResponse
)
def get_repository(
    repository_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_id)
):
    repository = get_repository_by_id(
        db,
        repository_id,
        current_user.id
    )

    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found"
        )

    return repository


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def remove_repository(
    repository_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_id)
):
    repository = get_repository_by_id(
        db,
        repository_id,
        current_user.id
    )

    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found"
        )

    delete_repository(db, repository)

    return None

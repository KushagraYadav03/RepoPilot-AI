
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_id, resolve_user_id
from app.schemas.ingestion import IngestionJobResponse
from app.schemas.repository import RepositoryCreate, RepositoryResponse
from app.services.ingestion_service import process_ingestion_job
from app.services.repository_service import RepositoryService


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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user_id),
):
    current_user_id = resolve_user_id(current_user)

    try:
        repository = RepositoryService.create_repository(
            db,
            data.name,
            str(data.github_url),
            current_user_id,
        )
    except ValueError as exc:
        if str(exc) == "Repository already exists for this user":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    job = RepositoryService.create_ingestion_job(db, repository.id, current_user_id)
    background_tasks.add_task(process_ingestion_job, job.id)

    return repository


@router.post(
    "/{repository_id}/refresh",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_repository(
    repository_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user_id),
):
    current_user_id = resolve_user_id(current_user)

    repository = RepositoryService.get_repository_by_id(
        db,
        repository_id,
        current_user_id,
    )

    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    job = RepositoryService.create_ingestion_job(db, repository.id, current_user_id)
    background_tasks.add_task(process_ingestion_job, job.id)

    return job


@router.get("", response_model=list[RepositoryResponse])
def list_repositories(
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user_id),
):
    current_user_id = resolve_user_id(current_user)
    return RepositoryService.list_repositories(db, current_user_id)


@router.get(
    "/{repository_id}",
    response_model=RepositoryResponse
)
def get_repository(
    repository_id: int,
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user_id),
):
    current_user_id = resolve_user_id(current_user)

    repository = RepositoryService.get_repository_by_id(
        db,
        repository_id,
        current_user_id,
    )

    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    return repository


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_repository(
    repository_id: int,
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user_id),
):
    current_user_id = resolve_user_id(current_user)

    repository = RepositoryService.get_repository_by_id(
        db,
        repository_id,
        current_user_id,
    )

    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    RepositoryService.delete_repository(db, repository)

    return None

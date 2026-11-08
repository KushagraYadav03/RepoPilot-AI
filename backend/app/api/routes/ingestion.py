
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_id, resolve_user_id
from app.models.ingestion_job import IngestionJob
from app.models.repository import Repository
from app.schemas.ingestion import (
    IngestionStartRequest,
    IngestionJobResponse,
)
from app.services.ingestion_service import process_ingestion_job


router = APIRouter(
    prefix="/ingestion",
    tags=["Repository Ingestion"],
)


@router.post(
    "/start",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_ingestion(
    request: IngestionStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user_id),
):
    """
    Create an ingestion job and run repository discovery
    in the background.
    """

    # Step 1: Extract authenticated user ID.
    user_id = resolve_user_id(current_user)

    # Step 2: Find repository.
    repository = db.get(
        Repository,
        request.repository_id,
    )

    # Step 3: Verify repository ownership.
    if repository is None or repository.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    # Step 4: Create ingestion job.
    job = IngestionJob(
        repository_id=repository.id,
        user_id=user_id,
        status="pending",
        total_files=0,
        processed_files=0,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    # Step 5: Schedule background processing.
    background_tasks.add_task(
        process_ingestion_job,
        job.id,
    )

    return job


@router.get(
    "/{job_id}",
    response_model=IngestionJobResponse,
)
async def get_ingestion_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user_id),
):
    """
    Get the current state of an ingestion job.
    """

    # Step 1: Extract authenticated user ID.
    user_id = resolve_user_id(current_user)

    # Step 2: Fetch ingestion job.
    job = db.get(
        IngestionJob,
        job_id,
    )

    # Step 3: Verify job ownership.
    if job is None or job.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    return job

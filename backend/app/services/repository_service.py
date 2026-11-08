from sqlalchemy.orm import Session

from app.models.ingestion_job import IngestionJob
from app.repositories.repository_repository import (
    create_repository as save_repository,
    delete_repository,
    get_repository_by_id,
    get_user_repositories,
    normalize_github_url,
    sanitize_repository_name,
)


class RepositoryService:
    @staticmethod
    def validate_name(name: str) -> str:
        return sanitize_repository_name(name)

    @staticmethod
    def normalize_url(github_url: str) -> str:
        return normalize_github_url(github_url)

    @staticmethod
    def create_repository(
        db: Session,
        name: str,
        github_url: str,
        owner_id: int,
    ):
        validated_name = RepositoryService.validate_name(name)
        normalized_url = RepositoryService.normalize_url(github_url)
        return save_repository(db, validated_name, normalized_url, owner_id)

    @staticmethod
    def create_ingestion_job(db: Session, repository_id: int, user_id: int):
        job = IngestionJob(
            repository_id=repository_id,
            user_id=user_id,
            status="pending",
            total_files=0,
            processed_files=0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def list_repositories(db: Session, owner_id: int):
        return get_user_repositories(db, owner_id)

    @staticmethod
    def get_repository_by_id(db: Session, repository_id: int, owner_id: int):
        return get_repository_by_id(db, repository_id, owner_id)

    @staticmethod
    def delete_repository(db: Session, repository):
        delete_repository(db, repository)

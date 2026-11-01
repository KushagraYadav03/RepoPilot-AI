
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.repository import Repository


def create_repository(
    db: Session,
    name: str,
    github_url: str,
    owner_id: int
):
    repository = Repository(
        name=name,
        github_url=github_url,
        owner_id=owner_id
    )

    db.add(repository)
    db.commit()
    db.refresh(repository)

    return repository


def get_user_repositories(db: Session, owner_id: int):
    statement = select(Repository).where(
        Repository.owner_id == owner_id
    )

    return db.scalars(statement).all()


def get_repository_by_id(
    db: Session,
    repository_id: int,
    owner_id: int
):
    statement = select(Repository).where(
        Repository.id == repository_id,
        Repository.owner_id == owner_id
    )

    return db.scalar(statement)


def delete_repository(db: Session, repository: Repository):
    db.delete(repository)
    db.commit()

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.repository import Repository


def sanitize_repository_name(name: str) -> str:
    cleaned_name = str(name).strip()

    if not cleaned_name:
        raise ValueError("Repository name is required")

    return cleaned_name


def normalize_github_url(github_url: str) -> str:
    parsed_url = urlparse(str(github_url).strip())
    hostname = (parsed_url.hostname or "").lower()

    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError("GitHub URL must use http or https")

    if hostname not in {"github.com", "www.github.com"}:
        raise ValueError("GitHub URL must point to github.com")

    path_parts = [part for part in parsed_url.path.split("/") if part]

    if len(path_parts) != 2:
        raise ValueError("GitHub URL must be in the format https://github.com/owner/repo")

    owner, repo = path_parts[0], path_parts[1].removesuffix(".git")

    if not owner or not repo:
        raise ValueError("GitHub URL must include both owner and repository name")

    return f"https://github.com/{owner}/{repo}"


def create_repository(
    db: Session,
    name: str,
    github_url: str,
    owner_id: int
):
    sanitized_name = sanitize_repository_name(name)
    normalized_url = normalize_github_url(github_url)

    existing_repository = db.scalar(
        select(Repository).where(
            Repository.owner_id == owner_id,
            Repository.github_url == normalized_url,
        )
    )

    if existing_repository is not None:
        raise ValueError("Repository already exists for this user")

    repository = Repository(
        name=sanitized_name,
        github_url=normalized_url,
        owner_id=owner_id,
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

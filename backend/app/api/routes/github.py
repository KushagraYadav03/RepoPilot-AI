
from fastapi import APIRouter

from app.services.git_service import (
    fetch_github_repo,
    fetch_github_tree
)

from app.schemas.github import (
    GitHubRepoResponse,
    GitHubTreeResponse
)


router = APIRouter(
    prefix="/github",
    tags=["GitHub"]
)


@router.get(
    "/repos/{owner}/{repo}",
    response_model=GitHubRepoResponse
)
async def get_github_repository(owner: str, repo: str):

    return await fetch_github_repo(owner, repo)


@router.get(
    "/repos/{owner}/{repo}/tree",
    response_model=GitHubTreeResponse
)
async def get_github_repository_tree(owner: str, repo: str):

    return await fetch_github_tree(owner, repo)

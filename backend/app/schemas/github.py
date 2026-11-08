from pydantic import BaseModel


class GitHubRepoResponse(BaseModel):

    name: str

    full_name: str

    description: str | None

    github_url: str

    stars: int

    forks: int

    language: str | None

    default_branch: str


class GitHubTreeFile(BaseModel):

    path: str

    sha: str

    size: int

    url: str | None = None


class GitHubTreeResponse(BaseModel):

    repository: str

    default_branch: str

    tree_sha: str | None = None

    truncated: bool

    total_files: int

    included_files: int

    skipped_files: int

    total_size: int

    files: list[GitHubTreeFile]

from pydantic import BaseModel, ConfigDict, Field


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


# ---------------------------------------------------------
# PULL REQUEST SCHEMAS
# ---------------------------------------------------------

class PullRequestSummary(BaseModel):
    number: int
    title: str
    state: str
    user_login: str | None = None
    html_url: str
    base_branch: str
    head_branch: str
    created_at: str | None = None
    updated_at: str | None = None


class PullRequestListResponse(BaseModel):
    repository: str
    count: int
    pull_requests: list[PullRequestSummary]


# ---------------------------------------------------------
# CHANGED FILE SCHEMA
# ---------------------------------------------------------

class ChangedFile(BaseModel):
    filename: str
    status: str
    additions: int = 0
    deletions: int = 0
    changes: int = 0

    patch: str | None = None
    patch_available: bool = False

    blob_url: str | None = None
    raw_url: str | None = None


# ---------------------------------------------------------
# DIFF RESPONSE
# ---------------------------------------------------------

class GitHubDiffResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repository: str
    diff_type: str
    identifier: str

    title: str | None = None
    message: str | None = None

    base_sha: str | None = None
    head_sha: str | None = None

    total_files: int
    additions: int
    deletions: int
    changes: int

    files_truncated: bool = False

    files: list[ChangedFile] = Field(default_factory=list)


import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.services import ingestion_service


class FakeScalarResult:
    def __init__(self, results=None):
        self.results = results or []

    def all(self):
        return self.results


class FakeDB:
    def __init__(self, job=None, repository=None):
        self.job = job
        self.repository = repository
        self.files = []
        self.chunks = []
        self.commits = []
        self.rollback_called = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def get(self, model, job_id):
        return self.job

    def add(self, instance):
        if isinstance(instance, ingestion_service.RepositoryFile):
            self.files.append(instance)
        elif isinstance(instance, ingestion_service.RepositoryChunk):
            self.chunks.append(instance)

    def scalar(self, query):
        sql = str(query).lower()

        if "repository_files" in sql:
            return self.files[0] if self.files else None

        return self.repository

    def scalars(self, query):
        sql = str(query).lower()

        if "repository_chunks" in sql:
            return FakeScalarResult(self.chunks)

        if "repository_files" in sql:
            return FakeScalarResult(self.files)

        return FakeScalarResult([])

    def delete(self, instance):
        if instance in self.files:
            self.files.remove(instance)

        if instance in self.chunks:
            self.chunks.remove(instance)

    def commit(self):
        self.commits.append(self.job.status)

    def rollback(self):
        self.rollback_called = True


def create_job():
    return SimpleNamespace(
        id=1,
        repository_id=10,
        user_id=5,
        status="pending",
        default_branch=None,
        tree_sha=None,
        total_files=0,
        processed_files=0,
        error_message=None,
    )


def create_repository():
    return SimpleNamespace(
        id=10,
        owner_id=5,
        github_url="https://github.com/example/project",
        default_branch=None,
        tree_sha=None,
        last_commit_sha=None,
        programming_languages=None,
        last_synced_at=None,
    )


def create_tree_data(files=None):
    if files is None:
        files = [
            {
                "path": "app/main.py",
                "url": (
                    "https://raw.githubusercontent.com/"
                    "example/project/main/app/main.py"
                ),
            }
        ]

    return {
        "default_branch": "main",
        "tree_sha": "abc123",
        "total_files": 100,
        "included_files": len(files),
        "skipped_files": 100 - len(files),
        "total_size": 10479,
        "truncated": False,
        "files": files,
    }


def create_processed_file(
    path="app/main.py",
    content="print('hello')\n",
    chunks=None,
):
    return {
        "file_path": path,
        "file_name": path.rsplit("/", 1)[-1],
        "content": content,
        "extension": ".py",
        "size": len(content.encode("utf-8")),
        "line_count": len(content.splitlines()),
        "chunks": chunks or [],
    }


def create_chunk():
    return {
        "file_path": "app/main.py",
        "symbol_name": "main",
        "symbol_kind": "function",
        "start_line": 1,
        "end_line": 3,
        "content": "def main():\n    return 'ok'\n",
        "commit_sha": "abc123",
    }


def mock_common_dependencies(monkeypatch, db, tree_data):
    monkeypatch.setattr(
        ingestion_service,
        "SessionLocal",
        lambda: db,
    )

    monkeypatch.setattr(
        ingestion_service,
        "fetch_github_tree",
        AsyncMock(return_value=tree_data),
    )

    monkeypatch.setattr(
        ingestion_service,
        "fetch_file_content",
        AsyncMock(return_value=b"print('hello')\n"),
    )

    monkeypatch.setattr(
        ingestion_service,
        "get_repository_file_point_ids",
        Mock(return_value=[]),
    )

    monkeypatch.setattr(
        ingestion_service,
        "delete_repository_points_by_ids",
        Mock(return_value=True),
    )

    monkeypatch.setattr(
        ingestion_service,
        "store_repository_embeddings",
        Mock(return_value=["point-1"]),
    )

    monkeypatch.setattr(
        ingestion_service,
        "embed_repository_chunks",
        Mock(side_effect=lambda chunks: [
            {**chunk, "embedding": [0.1, 0.2, 0.3]}
            for chunk in chunks
        ]),
    )


def test_ingestion_job_completes_successfully(monkeypatch):
    job = create_job()
    repository = create_repository()
    db = FakeDB(job, repository)

    tree_data = create_tree_data()

    mock_common_dependencies(monkeypatch, db, tree_data)

    monkeypatch.setattr(
        ingestion_service,
        "process_file",
        lambda path, content: create_processed_file(
            path=path,
            content=content.decode("utf-8"),
        ),
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(1)
    )

    assert job.status == "completed"
    assert job.default_branch == "main"
    assert job.tree_sha == "abc123"
    assert job.total_files == 1
    assert job.processed_files == 1
    assert job.error_message is None

    assert db.commits == ["processing", "completed"]
    assert len(db.files) == 1


def test_ingestion_calls_embedding_service_with_chunk_payload(
    monkeypatch,
):
    job = create_job()
    repository = create_repository()
    db = FakeDB(job, repository)

    chunk = create_chunk()
    tree_data = create_tree_data()

    mock_common_dependencies(monkeypatch, db, tree_data)

    monkeypatch.setattr(
        ingestion_service,
        "fetch_file_content",
        AsyncMock(
            return_value=b"def main():\n    return 'ok'\n"
        ),
    )

    monkeypatch.setattr(
        ingestion_service,
        "process_file",
        lambda path, content: create_processed_file(
            path=path,
            content=content.decode("utf-8"),
            chunks=[chunk],
        ),
    )

    embedded_chunks = [
        {
            **chunk,
            "embedding": [0.1, 0.2, 0.3],
        }
    ]

    embed_mock = Mock(return_value=embedded_chunks)

    monkeypatch.setattr(
        ingestion_service,
        "embed_repository_chunks",
        embed_mock,
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(1)
    )

    embed_mock.assert_called_once_with([chunk])

    ingestion_service.store_repository_embeddings.assert_called_once_with(
        embedded_chunks,
        repository_id=10,
    )

    assert job.status == "completed"
    assert job.processed_files == 1
    assert len(db.chunks) == 1


def test_ingestion_job_not_found(monkeypatch):
    db = FakeDB(job=None)

    monkeypatch.setattr(
        ingestion_service,
        "SessionLocal",
        lambda: db,
    )

    fetch_mock = AsyncMock()

    monkeypatch.setattr(
        ingestion_service,
        "fetch_github_tree",
        fetch_mock,
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(999)
    )

    fetch_mock.assert_not_called()
    assert db.commits == []


def test_ingestion_repository_not_found(monkeypatch):
    job = create_job()
    db = FakeDB(job=job, repository=None)

    monkeypatch.setattr(
        ingestion_service,
        "SessionLocal",
        lambda: db,
    )

    fetch_mock = AsyncMock()

    monkeypatch.setattr(
        ingestion_service,
        "fetch_github_tree",
        fetch_mock,
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(1)
    )

    assert job.status == "failed"
    assert job.error_message == (
        "Repository not found or access denied"
    )

    fetch_mock.assert_not_called()
    assert db.rollback_called is True


def test_ingestion_skips_duplicate_files_for_same_repo(
    monkeypatch,
):
    job = create_job()
    repository = create_repository()
    db = FakeDB(job, repository)

    tree_data = create_tree_data(
        files=[
            {
                "path": "app/main.py",
                "url": "https://example.com/app/main.py",
            },
            {
                "path": "app/main.py",
                "url": "https://example.com/app/main.py",
            },
        ]
    )

    mock_common_dependencies(monkeypatch, db, tree_data)

    fetch_mock = ingestion_service.fetch_file_content

    monkeypatch.setattr(
        ingestion_service,
        "process_file",
        lambda path, content: create_processed_file(
            path=path,
            content=content.decode("utf-8"),
        ),
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(1)
    )

    assert job.status == "completed"
    assert job.total_files == 1
    assert job.processed_files == 1
    assert len(db.files) == 1

    fetch_mock.assert_awaited_once()


def test_ingestion_fails_when_github_fetch_fails(monkeypatch):
    job = create_job()
    repository = create_repository()
    db = FakeDB(job, repository)

    monkeypatch.setattr(
        ingestion_service,
        "SessionLocal",
        lambda: db,
    )

    monkeypatch.setattr(
        ingestion_service,
        "fetch_github_tree",
        AsyncMock(
            side_effect=Exception("GitHub API error")
        ),
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(1)
    )

    assert job.status == "failed"
    assert job.error_message == "GitHub API error"
    assert db.rollback_called is True


def test_index_refresh_deletes_only_obsolete_points(monkeypatch):
    job = create_job()
    repository = create_repository()
    db = FakeDB(job, repository)

    existing_file = SimpleNamespace(
        repository_id=10,
        file_path="app/main.py",
        file_name="main.py",
        file_hash="old-hash",
        extension=".py",
        content="old content",
        size=12,
        line_count=1,
        ingestion_job_id=None,
    )

    db.files.append(existing_file)

    first_chunk = create_chunk()

    second_chunk = {
        **create_chunk(),
        "symbol_name": "helper",
        "start_line": 5,
        "end_line": 7,
        "content": "def helper():\n    return True\n",
    }

    new_content = "def main():\n    return 'new'\n"

    mock_common_dependencies(
        monkeypatch,
        db,
        create_tree_data(),
    )

    monkeypatch.setattr(
        ingestion_service,
        "fetch_file_content",
        AsyncMock(return_value=new_content.encode("utf-8")),
    )

    monkeypatch.setattr(
        ingestion_service,
        "process_file",
        lambda path, content: create_processed_file(
            path=path,
            content=content.decode("utf-8"),
            chunks=[first_chunk, second_chunk],
        ),
    )

    monkeypatch.setattr(
        ingestion_service,
        "get_repository_file_point_ids",
        Mock(
            return_value=[
                "old-point",
                "shared-point",
            ]
        ),
    )

    monkeypatch.setattr(
        ingestion_service,
        "store_repository_embeddings",
        Mock(
            return_value=[
                "new-point",
                "shared-point",
            ]
        ),
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(1)
    )

    ingestion_service.get_repository_file_point_ids.assert_called_once_with(
        repository_id=10,
        file_path="app/main.py",
    )

    ingestion_service.delete_repository_points_by_ids.assert_called_once_with(
        point_ids=["old-point"],
    )

    assert existing_file.file_hash == hashlib.sha256(
        new_content.encode("utf-8")
    ).hexdigest()

    assert job.status == "completed"


def test_unchanged_file_skips_embedding_and_qdrant_refresh(
    monkeypatch,
):
    job = create_job()
    repository = create_repository()
    db = FakeDB(job, repository)

    content = "print('hello')\n"

    existing_file = SimpleNamespace(
        repository_id=10,
        file_path="app/main.py",
        file_name="main.py",
        file_hash=hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest(),
        extension=".py",
        content=content,
        size=len(content),
        line_count=1,
        ingestion_job_id=None,
    )

    db.files.append(existing_file)

    mock_common_dependencies(
        monkeypatch,
        db,
        create_tree_data(),
    )

    process_mock = Mock(
        return_value=create_processed_file(
            content=content,
        )
    )

    monkeypatch.setattr(
        ingestion_service,
        "process_file",
        process_mock,
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(1)
    )

    ingestion_service.embed_repository_chunks.assert_not_called()
    ingestion_service.store_repository_embeddings.assert_not_called()
    ingestion_service.get_repository_file_point_ids.assert_not_called()
    ingestion_service.delete_repository_points_by_ids.assert_not_called()

    assert job.status == "completed"
    assert job.processed_files == 1


def test_embedding_failure_preserves_old_qdrant_points(
    monkeypatch,
):
    job = create_job()
    repository = create_repository()
    db = FakeDB(job, repository)

    chunk = create_chunk()

    mock_common_dependencies(
        monkeypatch,
        db,
        create_tree_data(),
    )

    monkeypatch.setattr(
        ingestion_service,
        "process_file",
        lambda path, content: create_processed_file(
            content=content.decode("utf-8"),
            chunks=[chunk],
        ),
    )

    monkeypatch.setattr(
        ingestion_service,
        "get_repository_file_point_ids",
        Mock(return_value=["old-point"]),
    )

    monkeypatch.setattr(
        ingestion_service,
        "embed_repository_chunks",
        Mock(
            side_effect=RuntimeError("Embedding failed")
        ),
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(1)
    )

    assert job.status == "failed"
    assert job.error_message == "Embedding failed"
    assert db.rollback_called is True

    ingestion_service.delete_repository_points_by_ids.assert_not_called()
    ingestion_service.store_repository_embeddings.assert_not_called()


def test_deleted_github_file_removes_old_vectors(monkeypatch):
    job = create_job()
    repository = create_repository()
    db = FakeDB(job, repository)

    deleted_file = SimpleNamespace(
        repository_id=10,
        file_path="app/removed.py",
        file_name="removed.py",
        file_hash="old-hash",
        extension=".py",
        content="old content",
        size=12,
        line_count=1,
        ingestion_job_id=None,
    )

    db.files.append(deleted_file)

    mock_common_dependencies(
        monkeypatch,
        db,
        create_tree_data(files=[]),
    )

    monkeypatch.setattr(
        ingestion_service,
        "get_repository_file_point_ids",
        Mock(return_value=["deleted-point"]),
    )

    asyncio.run(
        ingestion_service.process_ingestion_job(1)
    )

    assert job.status == "completed"
    assert deleted_file not in db.files

    ingestion_service.delete_repository_points_by_ids.assert_called_once_with(
        point_ids=["deleted-point"],
    )

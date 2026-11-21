
import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.sandbox import (
    SandboxLanguage,
    SandboxRequest,
)
from app.services.sandbox_service import SandboxService
from app.services.patch_validation_service import (
    PatchValidationService,
)


@pytest.fixture
def service():
    return SandboxService()


@pytest.fixture
def python_request():
    return SandboxRequest(
        language=SandboxLanguage.PYTHON,
        source_code="def add(a, b):\n    return a + b\n",
        test_code=(
            "from solution import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
        ),
    )


# ==================================================
# RESOURCE CONFIGURATION SAFETY
# ==================================================


@pytest.mark.parametrize(
    "field,value",
    [
        ("sandbox_timeout_seconds", 0),
        ("sandbox_timeout_seconds", 301),
        ("sandbox_cpu_limit", 0),
        ("sandbox_cpu_limit", -1),
        ("sandbox_cpu_limit", 9),
        ("sandbox_pids_limit", 0),
        ("sandbox_pids_limit", 5000),
        ("sandbox_max_output_bytes", 0),
        ("sandbox_max_output_bytes", 11_000_000),
        ("sandbox_memory_limit", "0m"),
        ("sandbox_memory_limit", "-256m"),
        ("sandbox_memory_limit", "invalid"),
    ],
)
def test_rejects_invalid_sandbox_configuration(field, value):

    with pytest.raises(ValidationError):

        Settings(
            database_url="sqlite:///test.db",
            _env_file=None,
            **{field: value},
        )


def test_accepts_valid_sandbox_configuration():

    config = Settings(
        database_url="sqlite:///test.db",
        _env_file=None,
        sandbox_timeout_seconds=10,
        sandbox_memory_limit="256m",
        sandbox_cpu_limit=0.5,
        sandbox_pids_limit=64,
        sandbox_max_output_bytes=65536,
    )

    assert config.sandbox_timeout_seconds == 10
    assert config.sandbox_memory_limit == "256m"
    assert config.sandbox_cpu_limit == 0.5
    assert config.sandbox_pids_limit == 64


# ==================================================
# DOCKER SECURITY CONFIGURATION
# ==================================================


def test_docker_network_is_disabled(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        language=SandboxLanguage.PYTHON,
        image="python-test-image",
        workspace=tmp_path,
        container_name="security-test",
        source_filename=source,
        test_filename=test,
    )

    network_index = command.index("--network")

    assert command[network_index + 1] == "none"


def test_docker_memory_limit_is_configured(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    index = command.index("--memory")

    assert command[index + 1] == service.memory_limit


def test_docker_cpu_limit_is_configured(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    index = command.index("--cpus")

    assert float(command[index + 1]) == service.cpu_limit


def test_docker_pid_limit_is_configured(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    index = command.index("--pids-limit")

    assert int(command[index + 1]) == service.pids_limit


def test_docker_root_filesystem_is_read_only(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    assert "--read-only" in command


def test_docker_runs_as_non_root(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    index = command.index("--user")

    assert command[index + 1] == "10001:10001"


def test_docker_drops_all_capabilities(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    index = command.index("--cap-drop")

    assert command[index + 1] == "ALL"


def test_docker_disables_privilege_escalation(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    index = command.index("--security-opt")

    assert command[index + 1] == "no-new-privileges"


def test_docker_tmpfs_is_restricted(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    index = command.index("--tmpfs")

    tmpfs_config = command[index + 1]

    assert "/tmp" in tmpfs_config
    assert "noexec" in tmpfs_config
    assert "nosuid" in tmpfs_config


def test_docker_has_automatic_container_cleanup(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    assert "--rm" in command


def test_docker_has_unique_container_name(
    service,
    python_request,
    tmp_path,
):

    source, test = service._get_filenames(python_request)

    command = service._build_command(
        SandboxLanguage.PYTHON,
        "python-test-image",
        tmp_path,
        "security-test",
        source,
        test,
    )

    index = command.index("--name")

    assert command[index + 1] == "security-test"


# ==================================================
# OUTPUT LIMIT SAFETY
# ==================================================


def test_output_reader_rejects_excessive_stdout():

    async def run_test():

        stream = asyncio.StreamReader()

        stream.feed_data(b"A" * 1000)
        stream.feed_eof()

        output, limited = await SandboxService._read_limited(
            stream,
            100,
        )

        assert len(output) == 100
        assert limited is True

    asyncio.run(run_test())


def test_output_reader_accepts_output_within_limit():

    async def run_test():

        stream = asyncio.StreamReader()

        stream.feed_data(b"Hello World")
        stream.feed_eof()

        output, limited = await SandboxService._read_limited(
            stream,
            100,
        )

        assert output == b"Hello World"
        assert limited is False

    asyncio.run(run_test())


def test_output_reader_handles_empty_output():

    async def run_test():

        stream = asyncio.StreamReader()
        stream.feed_eof()

        output, limited = await SandboxService._read_limited(
            stream,
            100,
        )

        assert output == b""
        assert limited is False

    asyncio.run(run_test())


# ==================================================
# EXECUTION TIMEOUT SAFETY
# ==================================================


class FakeTimeoutProcess:

    def __init__(self):

        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()

        self.stdout.feed_eof()
        self.stderr.feed_eof()

        self.returncode = None
        self.killed = False

    async def wait(self):

        if self.returncode is None:
            await asyncio.sleep(60)

        return self.returncode

    def kill(self):

        self.killed = True
        self.returncode = -9


def test_execution_timeout_stops_process_and_container(
    service,
    python_request,
    monkeypatch,
):

    service.timeout = 1

    process = None
    cleanup_calls = []

    monkeypatch.setattr(
        "app.services.sandbox_service.shutil.which",
        lambda executable: "docker",
    )

    async def fake_create_subprocess_exec(*args, **kwargs):

        nonlocal process

        process = FakeTimeoutProcess()

        return process

    async def fake_stop_container(
        container_name,
        docker_path=None,
    ):

        cleanup_calls.append(container_name)

    monkeypatch.setattr(
        "app.services.sandbox_service.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    monkeypatch.setattr(
        service,
        "_stop_container",
        fake_stop_container,
    )

    service.timeout = 0.05

    result = asyncio.run(
        service.execute(python_request)
    )

    assert result.timed_out is True
    assert result.passed is False
    assert result.exit_code is None

    assert process is not None
    assert process.killed is True

    assert len(cleanup_calls) == 1

    assert "timed out" in result.message.lower()


# ==================================================
# UNSAFE PATH REJECTION
# ==================================================


@pytest.mark.parametrize(
    "file_path",
    [
        "../evil.py",
        "/etc/passwd.py",
        "folder/../../evil.py",
        "folder//evil.py",
        "folder\\evil.py",
        "folder/evil.txt",
        "folder/\x00evil.py",
    ],
)
def test_patch_validation_rejects_unsafe_paths(file_path):

    with pytest.raises(HTTPException):

        PatchValidationService.validate_file_path(
            file_path
        )


def test_patch_validation_accepts_safe_path():

    result = PatchValidationService.validate_file_path(
        "src/utils/helper.py"
    )

    assert result == "src/utils/helper.py"


# ==================================================
# PATCH HEADER SAFETY
# ==================================================


def test_patch_rejects_binary_changes():

    patch = (
        "GIT binary patch\n"
        "binary content\n"
    )

    with pytest.raises(HTTPException):

        PatchValidationService.validate_patch_headers(
            patch,
            "main.py",
        )


def test_patch_rejects_path_mismatch():

    patch = (
        "--- a/other.py\n"
        "+++ b/other.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    with pytest.raises(HTTPException):

        PatchValidationService.validate_patch_headers(
            patch,
            "main.py",
        )


def test_patch_rejects_git_metadata():

    patch = (
        "diff --git a/main.py b/main.py\n"
        "--- a/main.py\n"
        "+++ b/main.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    with pytest.raises(HTTPException):

        PatchValidationService.validate_patch_headers(
            patch,
            "main.py",
        )


def test_patch_rejects_empty_patch():

    with pytest.raises(HTTPException):

        PatchValidationService.validate_patch_headers(
            "",
            "main.py",
        )

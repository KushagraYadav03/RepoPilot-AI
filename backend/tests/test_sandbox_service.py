
import asyncio

import pytest
from pydantic import ValidationError

from app.schemas.sandbox import (
    SandboxLanguage,
    SandboxRequest,
)
from app.services.sandbox_service import (
    SandboxExecutionError,
    SandboxService,
)


@pytest.fixture
def service():
    return SandboxService()


@pytest.fixture
def python_request():
    return SandboxRequest(
        language=SandboxLanguage.PYTHON,
        source_code="def add(a, b):\n    return a + b",
        test_code=(
            "from solution import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
        ),
    )


@pytest.fixture
def java_request():
    return SandboxRequest(
        language=SandboxLanguage.JAVA,
        source_code=(
            "public class Solution {\n"
            "    public int add(int a, int b) {\n"
            "        return a + b;\n"
            "    }\n"
            "}\n"
        ),
        test_code=(
            "import org.junit.jupiter.api.Test;\n"
            "import static org.junit.jupiter.api.Assertions.*;\n\n"
            "public class SolutionTest {\n"
            "    @Test\n"
            "    void testAdd() {\n"
            "        assertEquals(5, new Solution().add(2, 3));\n"
            "    }\n"
            "}\n"
        ),
    )


# ================================================
# TEST COUNT EXTRACTION
# ================================================


def test_extract_python_test_counts(service):
    passed, failed = service._extract_test_counts(
        SandboxLanguage.PYTHON,
        "3 passed, 2 failed in 0.20s",
        "",
    )

    assert passed == 3
    assert failed == 2


def test_extract_python_error_counts(service):
    passed, failed = service._extract_test_counts(
        SandboxLanguage.PYTHON,
        "2 passed, 1 error in 0.10s",
        "",
    )

    assert passed == 2
    assert failed == 1


def test_extract_python_collection_errors(service):
    passed, failed = service._extract_test_counts(
        SandboxLanguage.PYTHON,
        "1 error during collection",
        "",
    )

    assert passed == 0
    assert failed == 1


def test_extract_java_test_counts(service):
    passed, failed = service._extract_test_counts(
        SandboxLanguage.JAVA,
        (
            "[ 3 tests found ]\n"
            "[ 3 tests started ]\n"
            "[ 2 tests successful ]\n"
            "[ 1 tests failed ]"
        ),
        "",
    )

    assert passed == 2
    assert failed == 1


def test_extract_test_counts_from_stderr(service):
    passed, failed = service._extract_test_counts(
        SandboxLanguage.PYTHON,
        "",
        "1 passed, 2 failed",
    )

    assert passed == 1
    assert failed == 2


def test_extract_counts_when_no_summary_exists(service):
    passed, failed = service._extract_test_counts(
        SandboxLanguage.PYTHON,
        "Some unexpected output",
        "",
    )

    assert passed == 0
    assert failed == 0


# ================================================
# FILENAME TESTS
# ================================================


def test_python_default_filenames(service, python_request):
    source, test = service._get_filenames(python_request)

    assert source == "solution.py"
    assert test == "test_solution.py"


def test_java_default_filenames(service, java_request):
    source, test = service._get_filenames(java_request)

    assert source == "Solution.java"
    assert test == "SolutionTest.java"


def test_invalid_filename_is_rejected():
    with pytest.raises(ValidationError):
        SandboxRequest(
            language=SandboxLanguage.PYTHON,
            source_code="def add(a, b): return a + b",
            test_code="def test_add(): assert True",
            source_filename="../solution.py",
        )


def test_same_filename_is_rejected():
    with pytest.raises(ValidationError):
        SandboxRequest(
            language=SandboxLanguage.PYTHON,
            source_code="def add(a, b): return a + b",
            test_code="def test_add(): assert True",
            source_filename="solution.py",
            test_filename="solution.py",
        )


# ================================================
# DOCKER COMMAND TESTS
# ================================================


def test_python_docker_command_has_security_flags(
    service,
    python_request,
    tmp_path,
):
    source, test = service._get_filenames(python_request)

    command = service._build_command(
        language=SandboxLanguage.PYTHON,
        image="python-test-image",
        workspace=tmp_path,
        container_name="test-container",
        source_filename=source,
        test_filename=test,
        docker_path="docker",
    )

    assert "--network" in command
    assert "none" in command
    assert "--memory" in command
    assert "--cpus" in command
    assert "--pids-limit" in command
    assert "--read-only" in command
    assert "--cap-drop" in command
    assert "ALL" in command
    assert "--security-opt" in command
    assert "no-new-privileges" in command
    assert "pytest" in command
    assert test in command


def test_java_docker_command_uses_junit(
    service,
    java_request,
    tmp_path,
):
    source, test = service._get_filenames(java_request)

    command = service._build_command(
        language=SandboxLanguage.JAVA,
        image="java-test-image",
        workspace=tmp_path,
        container_name="test-container",
        source_filename=source,
        test_filename=test,
        docker_path="docker",
    )

    command_text = " ".join(command)

    assert "javac" in command_text
    assert "junit-platform-console-standalone.jar" in command_text
    assert "execute" in command_text
    assert source in command_text
    assert test in command_text


# ================================================
# MOCKED DOCKER EXECUTION TEST
# ================================================


class FakeProcess:

    def __init__(self, stdout_data, stderr_data):
        # This constructor must run inside an active event loop.
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()

        self.returncode = None

        self.stdout.feed_data(stdout_data)
        self.stdout.feed_eof()

        self.stderr.feed_data(stderr_data)
        self.stderr.feed_eof()

    async def wait(self):
        self.returncode = 0
        return 0

    def kill(self):
        self.returncode = -9


def test_execute_returns_test_counts(
    service,
    python_request,
    monkeypatch,
):

    monkeypatch.setattr(
        "app.services.sandbox_service.shutil.which",
        lambda executable: "docker",
    )

    async def run_execution():

        # Create FakeProcess after asyncio.run starts the event loop.
        fake_process = FakeProcess(
            stdout_data=b"2 passed in 0.10s\n",
            stderr_data=b"",
        )

        async def fake_create_subprocess_exec(*args, **kwargs):
            return fake_process

        monkeypatch.setattr(
            "app.services.sandbox_service.asyncio.create_subprocess_exec",
            fake_create_subprocess_exec,
        )

        return await service.execute(python_request)

    result = asyncio.run(run_execution())

    assert result.passed is True
    assert result.exit_code == 0
    assert result.passed_tests == 2
    assert result.failed_tests == 0
    assert "2 passed" in result.stdout
    assert result.timed_out is False
    assert result.output_limited is False


def test_execute_raises_when_docker_is_missing(
    service,
    python_request,
    monkeypatch,
):

    monkeypatch.setattr(
        "app.services.sandbox_service.shutil.which",
        lambda executable: None,
    )

    with pytest.raises(SandboxExecutionError):
        asyncio.run(
            service.execute(python_request)
        )

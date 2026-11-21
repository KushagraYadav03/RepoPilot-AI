
import asyncio
import logging
import re
import shlex
import shutil
import tempfile
import time
import uuid

from pathlib import Path, PurePosixPath

from app.core.config import settings

from app.schemas.sandbox import (
    SandboxLanguage,
    SandboxRequest,
    SandboxResponse,
)


logger = logging.getLogger(__name__)


class SandboxExecutionError(Exception):
    pass


class SandboxService:

    SAFE_PATH_SEGMENT = re.compile(
        r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$"
    )

    # ================================================
    # INITIALIZATION
    # ================================================

    def __init__(self):
        self.python_image = settings.sandbox_python_image
        self.java_image = settings.sandbox_java_image

        self.timeout = settings.sandbox_timeout_seconds

        self.memory_limit = settings.sandbox_memory_limit
        self.cpu_limit = settings.sandbox_cpu_limit
        self.pids_limit = settings.sandbox_pids_limit

        self.max_output_bytes = settings.sandbox_max_output_bytes

    # ================================================
    # MAIN EXECUTION METHOD
    # ================================================

    async def execute(
        self,
        request: SandboxRequest,
    ) -> SandboxResponse:

        docker_path = shutil.which("docker")

        if not docker_path:
            raise SandboxExecutionError(
                "Docker executable was not found. "
                "Install Docker Desktop and ensure it is running."
            )

        if self.timeout <= 0:
            raise SandboxExecutionError(
                "Sandbox timeout must be greater than zero."
            )

        if self.max_output_bytes <= 0:
            raise SandboxExecutionError(
                "Maximum output size must be greater than zero."
            )

        image = self._get_image(request.language)

        source_filename, test_filename = self._get_filenames(request)

        container_name = (
            f"repopilot-sandbox-{uuid.uuid4().hex[:12]}"
        )

        start_time = time.perf_counter()

        stdout = b""
        stderr = b""

        stdout_limited = False
        stderr_limited = False

        exit_code = None
        timed_out = False
        output_limited = False

        with tempfile.TemporaryDirectory(
            prefix="repopilot_sandbox_"
        ) as temporary_directory:

            workspace = Path(temporary_directory)

            source_path = workspace.joinpath(
                *PurePosixPath(source_filename).parts
            )

            test_path = workspace.joinpath(
                *PurePosixPath(test_filename).parts
            )

            source_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            test_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            source_path.write_text(
                request.source_code,
                encoding="utf-8",
            )

            test_path.write_text(
                request.test_code,
                encoding="utf-8",
            )

            command = self._build_command(
                language=request.language,
                image=image,
                workspace=workspace,
                container_name=container_name,
                source_filename=source_filename,
                test_filename=test_filename,
                docker_path=docker_path,
            )

            process = None
            stdout_task = None
            stderr_task = None

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout_limit = self.max_output_bytes // 2

                stderr_limit = (
                    self.max_output_bytes - stdout_limit
                )

                stdout_task = asyncio.create_task(
                    self._read_limited(
                        process.stdout,
                        stdout_limit,
                    )
                )

                stderr_task = asyncio.create_task(
                    self._read_limited(
                        process.stderr,
                        stderr_limit,
                    )
                )

                await asyncio.wait_for(
                    process.wait(),
                    timeout=self.timeout,
                )

                stdout_result, stderr_result = await asyncio.gather(
                    stdout_task,
                    stderr_task,
                )

                stdout, stdout_limited = stdout_result
                stderr, stderr_limited = stderr_result

                output_limited = (
                    stdout_limited or stderr_limited
                )

                exit_code = process.returncode

            except asyncio.TimeoutError:
                timed_out = True

                logger.warning(
                    "Sandbox execution timed out: %s",
                    container_name,
                )

                await self._stop_container(
                    container_name,
                    docker_path,
                )

                await self._terminate_process(process)

                (
                    stdout,
                    stderr,
                    stdout_limited,
                    stderr_limited,
                ) = await self._collect_remaining_output(
                    stdout_task,
                    stderr_task,
                )

                output_limited = (
                    stdout_limited or stderr_limited
                )

                stderr += (
                    b"\nTest execution exceeded "
                    b"the configured timeout."
                )

                exit_code = None

            except asyncio.CancelledError:
                logger.warning(
                    "Sandbox execution cancelled: %s",
                    container_name,
                )

                await self._stop_container(
                    container_name,
                    docker_path,
                )

                await self._terminate_process(process)

                await self._cancel_output_tasks(
                    stdout_task,
                    stderr_task,
                )

                raise

            except Exception as exc:
                logger.exception(
                    "Sandbox execution failed: %s",
                    container_name,
                )

                await self._stop_container(
                    container_name,
                    docker_path,
                )

                await self._terminate_process(process)

                await self._cancel_output_tasks(
                    stdout_task,
                    stderr_task,
                )

                raise SandboxExecutionError(
                    "Unable to execute tests inside Docker sandbox"
                ) from exc

        execution_time_ms = int(
            (time.perf_counter() - start_time) * 1000
        )

        stdout_text = stdout.decode(
            "utf-8",
            errors="replace",
        )

        stderr_text = stderr.decode(
            "utf-8",
            errors="replace",
        )

        if stdout_limited:
            stdout_text += "\n[Output truncated]"

        if stderr_limited:
            stderr_text += "\n[Output truncated]"

        passed_tests, failed_tests = self._extract_test_counts(
            language=request.language,
            stdout=stdout_text,
            stderr=stderr_text,
        )

        passed = (
            exit_code == 0
            and not timed_out
        )

        if timed_out:
            message = "Test execution timed out."

        elif passed:
            message = "All generated tests passed."

        else:
            message = "One or more generated tests failed."

        logger.info(
            "Sandbox execution completed: "
            "language=%s passed=%s timeout=%s exit_code=%s "
            "passed_tests=%s failed_tests=%s",
            request.language.value,
            passed,
            timed_out,
            exit_code,
            passed_tests,
            failed_tests,
        )

        return SandboxResponse(
            language=request.language,
            passed=passed,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            timed_out=timed_out,
            output_limited=output_limited,
            execution_time_ms=execution_time_ms,
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            message=message,
        )

    # ================================================
    # TEST RESULT COUNT EXTRACTION
    # ================================================

    @staticmethod
    def _extract_test_counts(
        language: SandboxLanguage,
        stdout: str,
        stderr: str,
    ) -> tuple[int, int]:

        output = f"{stdout}\n{stderr}"

        passed_tests = 0
        failed_tests = 0

        if language == SandboxLanguage.PYTHON:

            passed_match = re.search(
                r"(\d+)\s+passed\b",
                output,
                re.IGNORECASE,
            )

            failed_match = re.search(
                r"(\d+)\s+failed\b",
                output,
                re.IGNORECASE,
            )

            error_match = re.search(
                r"(\d+)\s+errors?\b",
                output,
                re.IGNORECASE,
            )

            if passed_match:
                passed_tests = int(passed_match.group(1))

            if failed_match:
                failed_tests += int(failed_match.group(1))

            if error_match:
                failed_tests += int(error_match.group(1))

        elif language == SandboxLanguage.JAVA:

            passed_match = re.search(
                r"(\d+)\s+tests?\s+successful\b",
                output,
                re.IGNORECASE,
            )

            failed_match = re.search(
                r"(\d+)\s+tests?\s+failed\b",
                output,
                re.IGNORECASE,
            )

            if passed_match:
                passed_tests = int(passed_match.group(1))

            if failed_match:
                failed_tests = int(failed_match.group(1))

        return passed_tests, failed_tests

    # ================================================
    # BOUNDED OUTPUT READER
    # ================================================

    @staticmethod
    async def _read_limited(
        stream,
        max_bytes: int,
    ) -> tuple[bytes, bool]:

        output = bytearray()
        output_limited = False

        while True:
            chunk = await stream.read(8192)

            if not chunk:
                break

            remaining = max_bytes - len(output)

            if remaining > 0:
                output.extend(chunk[:remaining])

            if len(chunk) > max(remaining, 0):
                output_limited = True

        return bytes(output), output_limited

    # ================================================
    # COLLECT REMAINING OUTPUT
    # ================================================

    @staticmethod
    async def _collect_remaining_output(
        stdout_task,
        stderr_task,
    ) -> tuple[bytes, bytes, bool, bool]:

        stdout = b""
        stderr = b""

        stdout_limited = False
        stderr_limited = False

        tasks = [
            task
            for task in (stdout_task, stderr_task)
            if task is not None
        ]

        if not tasks:
            return (
                stdout,
                stderr,
                stdout_limited,
                stderr_limited,
            )

        done, pending = await asyncio.wait(
            tasks,
            timeout=3,
        )

        for task in done:
            try:
                result, limited = task.result()

                if task is stdout_task:
                    stdout = result
                    stdout_limited = limited

                elif task is stderr_task:
                    stderr = result
                    stderr_limited = limited

            except Exception:
                logger.warning(
                    "Unable to collect sandbox output",
                    exc_info=True,
                )

        for task in pending:
            task.cancel()

        if pending:
            await asyncio.gather(
                *pending,
                return_exceptions=True,
            )

        return (
            stdout,
            stderr,
            stdout_limited,
            stderr_limited,
        )

    # ================================================
    # CANCEL OUTPUT TASKS
    # ================================================

    @staticmethod
    async def _cancel_output_tasks(
        stdout_task,
        stderr_task,
    ) -> None:

        tasks = [
            task
            for task in (stdout_task, stderr_task)
            if task is not None and not task.done()
        ]

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

    # ================================================
    # TERMINATE DOCKER CLI PROCESS
    # ================================================

    @staticmethod
    async def _terminate_process(
        process,
    ) -> None:

        if process is None:
            return

        if process.returncode is not None:
            return

        try:
            process.kill()

            await asyncio.wait_for(
                process.wait(),
                timeout=3,
            )

        except ProcessLookupError:
            pass

        except asyncio.TimeoutError:
            logger.error(
                "Unable to terminate Docker CLI process"
            )

    # ================================================
    # IMAGE SELECTION
    # ================================================

    def _get_image(
        self,
        language: SandboxLanguage,
    ) -> str:

        if language == SandboxLanguage.PYTHON:
            return self.python_image

        if language == SandboxLanguage.JAVA:
            return self.java_image

        raise SandboxExecutionError(
            "Unsupported sandbox language"
        )

    # ================================================
    # SAFE NESTED PATH VALIDATION
    # ================================================

    @classmethod
    def _validate_relative_filename(
        cls,
        filename: str,
        extension: str,
    ) -> str:

        if (
            not isinstance(filename, str)
            or not filename
            or len(filename) > 500
        ):
            raise SandboxExecutionError(
                "Invalid filename length"
            )

        if "\\" in filename or "\x00" in filename:
            raise SandboxExecutionError(
                "Unsafe filename"
            )

        path = PurePosixPath(filename)

        if path.is_absolute():
            raise SandboxExecutionError(
                "Absolute file paths are not allowed"
            )

        parts = filename.split("/")

        if any(
            not part
            or part in (".", "..")
            or not cls.SAFE_PATH_SEGMENT.fullmatch(part)
            for part in parts
        ):
            raise SandboxExecutionError(
                f"Unsafe file path: {filename}"
            )

        if path.suffix.lower() != extension.lower():
            raise SandboxExecutionError(
                f"Filename must have {extension} extension"
            )

        return path.as_posix()

    # ================================================
    # FILENAME VALIDATION
    # ================================================

    @classmethod
    def _get_filenames(
        cls,
        request: SandboxRequest,
    ) -> tuple[str, str]:

        if request.language == SandboxLanguage.PYTHON:

            source_filename = (
                request.source_filename or "solution.py"
            )

            test_filename = (
                request.test_filename or "test_solution.py"
            )

            extension = ".py"

        elif request.language == SandboxLanguage.JAVA:

            source_filename = (
                request.source_filename or "Solution.java"
            )

            test_filename = (
                request.test_filename or "SolutionTest.java"
            )

            extension = ".java"

        else:
            raise SandboxExecutionError(
                "Unsupported sandbox language"
            )

        source_filename = cls._validate_relative_filename(
            source_filename,
            extension,
        )

        test_filename = cls._validate_relative_filename(
            test_filename,
            extension,
        )

        if source_filename == test_filename:
            raise SandboxExecutionError(
                "Source filename and test filename must be different"
            )

        return source_filename, test_filename

    # ================================================
    # DOCKER COMMAND BUILDER
    # ================================================

    def _build_command(
        self,
        language: SandboxLanguage,
        image: str,
        workspace: Path,
        container_name: str,
        source_filename: str,
        test_filename: str,
        docker_path: str | None = None,
    ) -> list[str]:

        command = [
            docker_path or "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--memory",
            self.memory_limit,
            "--cpus",
            str(self.cpu_limit),
            "--pids-limit",
            str(self.pids_limit),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--label",
            "repopilot.sandbox=true",
            "--mount",
            (
                f"type=bind,"
                f"source={workspace.resolve()},"
                f"target=/workspace"
            ),
            "--workdir",
            "/workspace",
            image,
        ]

        if language == SandboxLanguage.PYTHON:

            command.extend([
                "python",
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                "-p",
                "no:cacheprovider",
                test_filename,
            ])

        elif language == SandboxLanguage.JAVA:

            junit_jar = (
                "/opt/junit/"
                "junit-platform-console-standalone.jar"
            )

            quoted_source = shlex.quote(source_filename)
            quoted_test = shlex.quote(test_filename)
            quoted_jar = shlex.quote(junit_jar)

            java_command = (
                "mkdir -p /tmp/classes && "
                f"javac -cp {quoted_jar} "
                f"-d /tmp/classes "
                f"{quoted_source} {quoted_test} && "
                f"java -jar {quoted_jar} execute "
                "--class-path /tmp/classes "
                "--scan-class-path"
            )

            command.extend([
                "sh",
                "-c",
                java_command,
            ])

        else:
            raise SandboxExecutionError(
                "Unsupported sandbox language"
            )

        return command

    # ================================================
    # CONTAINER CLEANUP
    # ================================================

    @staticmethod
    async def _stop_container(
        container_name: str,
        docker_path: str | None = None,
    ) -> None:

        process = None

        try:
            process = await asyncio.create_subprocess_exec(
                docker_path or "docker",
                "rm",
                "-f",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            await asyncio.wait_for(
                process.wait(),
                timeout=5,
            )

        except asyncio.TimeoutError:
            logger.error(
                "Docker container cleanup timed out: %s",
                container_name,
            )

            await SandboxService._terminate_process(
                process
            )

        except Exception:
            logger.warning(
                "Unable to remove sandbox container %s",
                container_name,
                exc_info=True,
            )

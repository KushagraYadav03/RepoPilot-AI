
import logging
import re
import shutil
import subprocess
import tempfile

from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from app.schemas.sandbox import SandboxLanguage, SandboxRequest
from app.services.sandbox_service import SandboxService


logger = logging.getLogger(__name__)

MAX_SOURCE_FILE_SIZE = 50 * 1024
MAX_PATCH_SIZE = 100 * 1024
MAX_TEST_FILE_SIZE = 50 * 1024
GIT_TIMEOUT_SECONDS = 15

SAFE_PATH_SEGMENT = re.compile(
    r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$"
)

PATCH_OLD_HEADER = re.compile(
    r"^--- a/(.+)$",
    re.MULTILINE,
)

PATCH_NEW_HEADER = re.compile(
    r"^\+\+\+ b/(.+)$",
    re.MULTILINE,
)


class PatchValidationService:

    def __init__(self, sandbox_service=None):
        self.sandbox_service = (
            sandbox_service
            if sandbox_service is not None
            else SandboxService()
        )

    @staticmethod
    def validate_file_path(file_path: str) -> str:

        if (
            not isinstance(file_path, str)
            or not file_path.strip()
            or "\x00" in file_path
            or "\\" in file_path
        ):
            raise HTTPException(
                status_code=422,
                detail="Invalid file path",
            )

        path = PurePosixPath(file_path)

        if path.is_absolute():
            raise HTTPException(
                status_code=422,
                detail="Absolute file paths are not allowed",
            )

        parts = file_path.split("/")

        if any(part in {"", ".", ".."} for part in parts):
            raise HTTPException(
                status_code=422,
                detail="Unsafe file path",
            )

        if path.as_posix() != file_path:
            raise HTTPException(
                status_code=422,
                detail="Invalid file path format",
            )

        if len(file_path) > 500:
            raise HTTPException(
                status_code=422,
                detail="File path is too long",
            )

        if any(
            not SAFE_PATH_SEGMENT.fullmatch(part)
            for part in parts
        ):
            raise HTTPException(
                status_code=422,
                detail="File path contains unsupported characters",
            )

        if path.suffix.lower() not in {".py", ".java"}:
            raise HTTPException(
                status_code=422,
                detail="Only Python and Java files are supported",
            )

        return path.as_posix()

    @staticmethod
    def validate_language(
        file_path: str,
        language: SandboxLanguage,
    ) -> None:

        expected_extension = (
            ".py"
            if language == SandboxLanguage.PYTHON
            else ".java"
        )

        if PurePosixPath(file_path).suffix.lower() != expected_extension:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"The selected file must end in "
                    f"{expected_extension} for {language.value}"
                ),
            )

    @staticmethod
    def validate_test_filename(
        test_filename: str | None,
        language: SandboxLanguage,
        source_file_path: str,
    ) -> str:

        source_path = PurePosixPath(source_file_path)

        if test_filename is None:
            if language == SandboxLanguage.PYTHON:
                return f"test_{source_path.stem}.py"

            return f"{source_path.stem}Test.java"

        if (
            not isinstance(test_filename, str)
            or not test_filename
            or len(test_filename) > 100
            or "\x00" in test_filename
            or "/" in test_filename
            or "\\" in test_filename
            or test_filename in {".", ".."}
        ):
            raise HTTPException(
                status_code=422,
                detail="Test filename must be a safe simple filename",
            )

        path = PurePosixPath(test_filename)

        if len(path.parts) != 1:
            raise HTTPException(
                status_code=422,
                detail="Test filename cannot contain directories",
            )

        if not SAFE_PATH_SEGMENT.fullmatch(path.stem):
            raise HTTPException(
                status_code=422,
                detail="Test filename contains unsupported characters",
            )

        expected_extension = (
            ".py"
            if language == SandboxLanguage.PYTHON
            else ".java"
        )

        if path.suffix.lower() != expected_extension:
            raise HTTPException(
                status_code=422,
                detail=f"Test filename must end in {expected_extension}",
            )

        if path.name == source_path.name:
            raise HTTPException(
                status_code=422,
                detail="Source and test filenames must be different",
            )

        return path.name

    @staticmethod
    def validate_patch_headers(
        patch: str,
        file_path: str,
    ) -> None:

        if not isinstance(patch, str) or not patch.strip():
            raise HTTPException(
                status_code=422,
                detail="Patch cannot be empty",
            )

        try:
            patch_size = len(patch.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise HTTPException(
                status_code=422,
                detail="Patch contains invalid text encoding",
            ) from exc

        if patch_size > MAX_PATCH_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Patch exceeds the allowed size",
            )

        if "\x00" in patch:
            raise HTTPException(
                status_code=422,
                detail="Binary patches are not supported",
            )

        if (
            "GIT binary patch" in patch
            or "Binary files " in patch
            or "new file mode " in patch
            or "deleted file mode " in patch
            or "rename from " in patch
            or "rename to " in patch
        ):
            raise HTTPException(
                status_code=422,
                detail="Only text modifications to an existing file are allowed",
            )

        if re.search(r"^diff --git ", patch, re.MULTILINE):
            raise HTTPException(
                status_code=422,
                detail="Git metadata headers are not accepted",
            )

        old_headers = PATCH_OLD_HEADER.findall(patch)
        new_headers = PATCH_NEW_HEADER.findall(patch)

        if len(old_headers) != 1 or len(new_headers) != 1:
            raise HTTPException(
                status_code=422,
                detail="Patch must contain exactly one old and one new file header",
            )

        expected_path = PatchValidationService.validate_file_path(
            file_path
        )

        old_path = old_headers[0]
        new_path = new_headers[0]

        if old_path != expected_path or new_path != expected_path:
            raise HTTPException(
                status_code=422,
                detail="Patch headers do not match the selected file",
            )

        if not re.search(r"^@@ ", patch, re.MULTILINE):
            raise HTTPException(
                status_code=422,
                detail="Patch does not contain a valid unified diff hunk",
            )

    @staticmethod
    def get_default_test_filename(
        file_path: str,
        language: SandboxLanguage,
    ) -> str:

        source_path = PurePosixPath(file_path)

        if language == SandboxLanguage.PYTHON:
            return f"test_{source_path.stem}.py"

        return f"{source_path.stem}Test.java"

    @staticmethod
    def _run_git_command(
        command: list[str],
        workspace: Path,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess:

        try:
            return subprocess.run(
                command,
                cwd=str(workspace),
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=GIT_TIMEOUT_SECONDS,
                check=False,
            )

        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                status_code=504,
                detail="Git patch operation timed out",
            ) from exc

        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail="Git executable is not available on the server",
            ) from exc

        except OSError as exc:
            logger.exception("Git command execution failed")

            raise HTTPException(
                status_code=500,
                detail="Unable to execute Git patch operation",
            ) from exc

    def apply_patch_in_workspace(
        self,
        original_source: str,
        patch: str,
        file_path: str,
    ) -> str:

        safe_file_path = self.validate_file_path(file_path)

        if not isinstance(original_source, str) or not original_source:
            raise HTTPException(
                status_code=422,
                detail="Original source code is empty or invalid",
            )

        try:
            source_size = len(original_source.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise HTTPException(
                status_code=422,
                detail="Original source contains invalid text encoding",
            ) from exc

        if source_size > MAX_SOURCE_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Original source exceeds the allowed size",
            )

        self.validate_patch_headers(
            patch=patch,
            file_path=safe_file_path,
        )

        if shutil.which("git") is None:
            raise HTTPException(
                status_code=503,
                detail="Git executable is not available on the server",
            )

        with tempfile.TemporaryDirectory(
            prefix="repopilot_patch_"
        ) as temporary_directory:

            workspace = Path(temporary_directory)

            source_path = workspace.joinpath(
                *PurePosixPath(safe_file_path).parts
            )

            source_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            source_path.write_text(
                original_source,
                encoding="utf-8",
            )

            init_result = self._run_git_command(
                ["git", "init", "--quiet"],
                workspace,
            )

            if init_result.returncode != 0:
                logger.error(
                    "Git init failed: %s",
                    init_result.stderr,
                )

                raise HTTPException(
                    status_code=500,
                    detail="Unable to initialize temporary patch workspace",
                )

            check_result = self._run_git_command(
                [
                    "git",
                    "apply",
                    "--check",
                    "--whitespace=nowarn",
                    "-",
                ],
                workspace,
                input_text=patch,
            )

            if check_result.returncode != 0:
                logger.warning(
                    "Git patch check rejected patch: %s",
                    check_result.stderr,
                )

                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Patch cannot be applied to the current GitHub source: "
                        f"{check_result.stderr.strip()[:1000]}"
                    ),
                )

            apply_result = self._run_git_command(
                [
                    "git",
                    "apply",
                    "--whitespace=nowarn",
                    "-",
                ],
                workspace,
                input_text=patch,
            )

            if apply_result.returncode != 0:
                logger.warning(
                    "Git patch application failed: %s",
                    apply_result.stderr,
                )

                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Unable to apply patch: "
                        f"{apply_result.stderr.strip()[:1000]}"
                    ),
                )

            if not source_path.is_file():
                raise HTTPException(
                    status_code=422,
                    detail="Patched source file was not found",
                )

            try:
                updated_source = source_path.read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Unable to read patched source file",
                ) from exc

            if not updated_source.strip():
                raise HTTPException(
                    status_code=422,
                    detail="Patched source file is empty",
                )

            if len(updated_source.encode("utf-8")) > MAX_SOURCE_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail="Patched source exceeds the allowed size",
                )

            return updated_source

    async def validate_and_execute(
        self,
        file_path: str,
        original_source: str,
        patch: str,
        language: SandboxLanguage,
        test_code: str,
        test_filename: str | None = None,
    ) -> dict:

        safe_file_path = self.validate_file_path(file_path)

        self.validate_language(
            file_path=safe_file_path,
            language=language,
        )

        if not isinstance(test_code, str) or not test_code.strip():
            raise HTTPException(
                status_code=422,
                detail="Test code cannot be empty",
            )

        if "\x00" in test_code:
            raise HTTPException(
                status_code=422,
                detail="Test code cannot contain null bytes",
            )

        if len(test_code.encode("utf-8")) > MAX_TEST_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Test code exceeds the allowed size",
            )

        safe_test_filename = self.validate_test_filename(
            test_filename=test_filename,
            language=language,
            source_file_path=safe_file_path,
        )

        updated_source = self.apply_patch_in_workspace(
            original_source=original_source,
            patch=patch,
            file_path=safe_file_path,
        )

        sandbox_request = SandboxRequest(
            language=language,
            source_code=updated_source,
            test_code=test_code,
            source_filename=safe_file_path,
            test_filename=safe_test_filename,
        )

        try:
            sandbox_response = await self.sandbox_service.execute(
                sandbox_request
            )

        except HTTPException:
            raise

        except Exception as exc:
            logger.exception(
                "Sandbox execution failed during patch validation"
            )

            raise HTTPException(
                status_code=502,
                detail="Unable to execute patched source in sandbox",
            ) from exc

        return {
            "patch_applied": True,
            "source_matches": True,
            "sandbox": sandbox_response,
            "message": (
                "Patch was applied successfully to the fetched GitHub source "
                "and the patched source was executed in the sandbox."
            ),
        }

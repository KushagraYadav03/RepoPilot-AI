
import asyncio
import json
import logging
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

from pathlib import Path
from typing import Any

from app.schemas.code_review import (
    ReviewFinding,
    ReviewSeverity,
)

from app.services.git_service import (
    fetch_github_file_content,
)


logger = logging.getLogger(__name__)


PYTHON_EXTENSIONS = {".py"}
JAVA_EXTENSIONS = {".java"}


class StaticAnalysisService:
    """
    Runs static analysis on complete source files changed
    in a GitHub pull request or commit.

    Python:
        Ruff

    Java:
        PMD CLI
    """

    async def analyze_changed_files(
        self,
        owner: str,
        repo: str,
        ref: str,
        files: list[dict[str, Any]],
    ) -> list[ReviewFinding]:

        if not owner or not repo or not ref:
            return []

        if not isinstance(files, list):
            return []

        findings: list[ReviewFinding] = []

        for file_data in files:

            if not isinstance(file_data, dict):
                continue

            filename = file_data.get("filename", "")
            status = file_data.get("status", "")

            if not filename or status == "removed":
                continue

            extension = Path(filename).suffix.lower()

            if (
                extension not in PYTHON_EXTENSIONS
                and extension not in JAVA_EXTENSIONS
            ):
                continue

            try:
                source_code = await fetch_github_file_content(
                    owner=owner,
                    repo=repo,
                    file_path=filename,
                    ref=ref,
                )

            except Exception:
                logger.exception(
                    "Unable to fetch source file for static analysis: %s",
                    filename,
                )
                continue

            if not isinstance(source_code, str) or not source_code:
                logger.warning(
                    "Skipping static analysis because source is unavailable: %s",
                    filename,
                )
                continue

            if extension in PYTHON_EXTENSIONS:

                file_findings = await self._run_ruff(
                    filename=filename,
                    source_code=source_code,
                )

            else:

                file_findings = await self._run_pmd(
                    filename=filename,
                    source_code=source_code,
                )

            findings.extend(file_findings)

        logger.info(
            "Static analysis completed for %s/%s: %s findings",
            owner,
            repo,
            len(findings),
        )

        return findings

    # =====================================================
    # RUFF - PYTHON STATIC ANALYSIS
    # =====================================================

    async def _run_ruff(
        self,
        filename: str,
        source_code: str,
    ) -> list[ReviewFinding]:

        ruff_path = shutil.which("ruff")

        if ruff_path:
            command = [
                ruff_path,
                "check",
                "--output-format",
                "json",
                "--stdin-filename",
                filename,
                "-",
            ]
        else:
            command = [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--output-format",
                "json",
                "--stdin-filename",
                filename,
                "-",
            ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate(
                input=source_code.encode("utf-8")
            )

        except FileNotFoundError:
            logger.warning(
                "Ruff is not installed. Skipping Python static analysis."
            )
            return []

        except Exception:
            logger.exception(
                "Ruff execution failed for %s",
                filename,
            )
            return []

        # Ruff return codes:
        # 0 = no violations
        # 1 = violations found
        # Other codes = execution/configuration error

        if process.returncode not in (0, 1):

            logger.error(
                "Ruff failed for %s: %s",
                filename,
                stderr.decode("utf-8", errors="replace")[:1000],
            )

            return []

        try:
            diagnostics = json.loads(
                stdout.decode("utf-8")
            )

        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.error(
                "Ruff returned invalid JSON for %s",
                filename,
            )
            return []

        if not isinstance(diagnostics, list):
            return []

        findings = []

        for diagnostic in diagnostics:

            if not isinstance(diagnostic, dict):
                continue

            code = diagnostic.get("code") or "RUFF"
            message = diagnostic.get("message") or (
                "Static analysis issue detected."
            )

            location = diagnostic.get("location") or {}
            end_location = diagnostic.get("end_location") or {}

            start_line = location.get("row", 1)
            end_line = end_location.get("row", start_line)

            start_line = max(1, int(start_line or 1))
            end_line = max(start_line, int(end_line or start_line))

            severity = self._ruff_severity(code)

            evidence = self._get_evidence(
                source_code,
                start_line,
            )

            findings.append(
                ReviewFinding(
                    severity=severity,
                    title=f"Ruff: {message}",
                    location={
                        "file_path": filename,
                        "start_line": start_line,
                        "end_line": end_line,
                    },
                    evidence=evidence,
                    explanation=(
                        f"Ruff detected rule {code}: {message}"
                    ),
                    suggestion=(
                        diagnostic.get("message")
                        or "Fix the reported Ruff violation."
                    ),
                    rule_id=f"RUFF:{code}",
                    confidence=1.0,
                )
            )

        return findings

    @staticmethod
    def _ruff_severity(code: str) -> ReviewSeverity:
        """
        Map Ruff rule families to review severities.

        This is a practical severity mapping, not a claim
        that every rule in a family has identical impact.
        """

        if code.startswith(("S", "F")):
            return ReviewSeverity.HIGH

        if code.startswith(("E", "B")):
            return ReviewSeverity.MEDIUM

        if code.startswith(("I", "UP", "SIM")):
            return ReviewSeverity.LOW

        return ReviewSeverity.INFO

    # =====================================================
    # PMD - JAVA STATIC ANALYSIS
    # =====================================================

    async def _run_pmd(
        self,
        filename: str,
        source_code: str,
    ) -> list[ReviewFinding]:

        pmd_path = shutil.which("pmd")

        if not pmd_path:
            logger.warning(
                "PMD CLI is not installed. Skipping Java analysis for %s",
                filename,
            )
            return []

        try:
            with tempfile.TemporaryDirectory() as temp_dir:

                source_path = Path(temp_dir) / Path(filename).name

                source_path.write_text(
                    source_code,
                    encoding="utf-8",
                )

                command = [
                    pmd_path,
                    "check",
                    "--dir",
                    temp_dir,
                    "--rulesets",
                    "rulesets/java/quickstart.xml",
                    "--format",
                    "xml",
                ]

                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await process.communicate()

                # PMD can return a non-zero status when violations
                # are found. Parse the XML output in either case.

                if not stdout:
                    logger.error(
                        "PMD returned no output for %s: %s",
                        filename,
                        stderr.decode(
                            "utf-8",
                            errors="replace",
                        )[:1000],
                    )
                    return []

                return self._parse_pmd_xml(
                    filename=filename,
                    source_code=source_code,
                    xml_output=stdout.decode(
                        "utf-8",
                        errors="replace",
                    ),
                )

        except FileNotFoundError:
            logger.warning(
                "PMD executable could not be started."
            )
            return []

        except Exception:
            logger.exception(
                "PMD execution failed for %s",
                filename,
            )
            return []

    def _parse_pmd_xml(
        self,
        filename: str,
        source_code: str,
        xml_output: str,
    ) -> list[ReviewFinding]:

        try:
            root = ET.fromstring(xml_output)

        except ET.ParseError:
            logger.exception(
                "Unable to parse PMD XML output for %s",
                filename,
            )
            return []

        findings = []

        for violation in root.iter("violation"):

            try:
                start_line = int(
                    violation.attrib.get("beginline", "1")
                )

                end_line = int(
                    violation.attrib.get(
                        "endline",
                        str(start_line),
                    )
                )

            except ValueError:
                continue

            start_line = max(1, start_line)
            end_line = max(start_line, end_line)

            rule = violation.attrib.get(
                "rule",
                "UnknownRule",
            )

            priority = violation.attrib.get(
                "priority",
                "3",
            )

            message = (
                violation.text or ""
            ).strip()

            severity = self._pmd_severity(priority)

            evidence = self._get_evidence(
                source_code,
                start_line,
            )

            findings.append(
                ReviewFinding(
                    severity=severity,
                    title=f"PMD: {rule}",
                    location={
                        "file_path": filename,
                        "start_line": start_line,
                        "end_line": end_line,
                    },
                    evidence=evidence,
                    explanation=(
                        message
                        or f"PMD detected rule {rule}."
                    ),
                    suggestion=(
                        "Review the PMD rule and update the affected code."
                    ),
                    rule_id=f"PMD:{rule}",
                    confidence=1.0,
                )
            )

        return findings

    @staticmethod
    def _pmd_severity(priority: str) -> ReviewSeverity:

        mapping = {
            "1": ReviewSeverity.CRITICAL,
            "2": ReviewSeverity.HIGH,
            "3": ReviewSeverity.MEDIUM,
            "4": ReviewSeverity.LOW,
            "5": ReviewSeverity.INFO,
        }

        return mapping.get(
            str(priority),
            ReviewSeverity.MEDIUM,
        )

    # =====================================================
    # COMMON HELPERS
    # =====================================================

    @staticmethod
    def _get_evidence(
        source_code: str,
        line_number: int,
    ) -> str:

        lines = source_code.splitlines()

        if not lines:
            return "Source code is unavailable."

        index = line_number - 1

        if index < 0 or index >= len(lines):
            return "Source line is unavailable."

        return lines[index].strip() or "(blank line)"

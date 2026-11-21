
import asyncio
import logging

from app.schemas.sandbox import (
    SandboxLanguage,
    SandboxRequest,
)

from app.services.sandbox_service import SandboxService


logging.basicConfig(level=logging.INFO)


async def main():

    service = SandboxService()

    # ============================================
    # TEST 1: PYTHON EXECUTION
    # ============================================

    print("\n========== PYTHON EXECUTION ==========")

    python_request = SandboxRequest(
        language=SandboxLanguage.PYTHON,

        source_code=(
            "def add(a, b):\n"
            "    return a + b\n"
        ),

        test_code=(
            "from solution import add\n"
            "\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
        ),
    )

    python_result = await service.execute(
        python_request
    )

    print("Passed:", python_result.passed)
    print("Exit code:", python_result.exit_code)
    print("Timed out:", python_result.timed_out)
    print("Execution time:", python_result.execution_time_ms)
    print("STDOUT:\n", python_result.stdout)
    print("STDERR:\n", python_result.stderr)

    assert python_result.passed is True
    assert python_result.exit_code == 0
    assert python_result.timed_out is False

    print("PYTHON TEST: PASSED")

    # ============================================
    # TEST 2: JAVA EXECUTION
    # ============================================

    print("\n========== JAVA EXECUTION ==========")

    java_request = SandboxRequest(
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
            "import static org.junit.jupiter.api.Assertions.assertEquals;\n"
            "\n"
            "public class SolutionTest {\n"
            "\n"
            "    @Test\n"
            "    void testAdd() {\n"
            "        Solution solution = new Solution();\n"
            "        assertEquals(5, solution.add(2, 3));\n"
            "    }\n"
            "}\n"
        ),
    )

    java_result = await service.execute(
        java_request
    )

    print("Passed:", java_result.passed)
    print("Exit code:", java_result.exit_code)
    print("Timed out:", java_result.timed_out)
    print("Execution time:", java_result.execution_time_ms)
    print("STDOUT:\n", java_result.stdout)
    print("STDERR:\n", java_result.stderr)

    assert java_result.passed is True
    assert java_result.exit_code == 0
    assert java_result.timed_out is False

    print("JAVA TEST: PASSED")

    # ============================================
    # TEST 3: TIMEOUT VERIFICATION
    # ============================================

    print("\n========== TIMEOUT VERIFICATION ==========")

    timeout_request = SandboxRequest(
        language=SandboxLanguage.PYTHON,

        source_code=(
            "def run_forever():\n"
            "    while True:\n"
            "        pass\n"
        ),

        test_code=(
            "from solution import run_forever\n"
            "\n"
            "def test_timeout():\n"
            "    run_forever()\n"
        ),
    )

    timeout_result = await service.execute(
        timeout_request
    )

    print("Passed:", timeout_result.passed)
    print("Exit code:", timeout_result.exit_code)
    print("Timed out:", timeout_result.timed_out)
    print("Execution time:", timeout_result.execution_time_ms)
    print("STDERR:\n", timeout_result.stderr)

    assert timeout_result.passed is False
    assert timeout_result.timed_out is True
    assert timeout_result.exit_code is None

    print("TIMEOUT TEST: PASSED")

    # ============================================
    # FINAL RESULT
    # ============================================

    print("\n========================================")
    print("ALL SANDBOX INTEGRATION TESTS PASSED")
    print("Python execution: PASSED")
    print("Java execution: PASSED")
    print("Timeout verification: PASSED")
    print("========================================")


if __name__ == "__main__":

    asyncio.run(main())

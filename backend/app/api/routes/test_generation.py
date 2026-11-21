
import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.core.dependencies import get_current_user_id

from app.schemas.test_generation import (
    GenerateTestsRequest,
    GenerateTestsResponse,
)

from app.services.test_generation_service import (
    TestGenerationService,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    tags=["Test Generation"],
)


test_generation_service = TestGenerationService()


@router.post(
    "/tests/generate",
    response_model=GenerateTestsResponse,
    status_code=status.HTTP_200_OK,
)
@router.post(
    "/test-generation",
    response_model=GenerateTestsResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def generate_tests(
    request: GenerateTestsRequest,
    current_user_id: int = Depends(get_current_user_id),
):
    try:
        generated_tests = (
            await test_generation_service.generate_tests(
                request=request,
            )
        )

        return generated_tests

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "Test generation failed for user %s",
            current_user_id,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to generate tests",
        ) from exc

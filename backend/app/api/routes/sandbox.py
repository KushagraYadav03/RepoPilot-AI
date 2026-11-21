
import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.core.dependencies import get_current_user_id

from app.schemas.sandbox import (
    SandboxRequest,
    SandboxResponse,
)

from app.services.sandbox_service import (
    SandboxExecutionError,
    SandboxService,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Docker Sandbox"],
)

sandbox_service = SandboxService()


@router.post(
    "/sandbox/execute",
    response_model=SandboxResponse,
    status_code=status.HTTP_200_OK,
)
async def execute_sandbox(
    request: SandboxRequest,
    current_user_id: int = Depends(get_current_user_id),
):

    try:
        return await sandbox_service.execute(request)

    except SandboxExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "Sandbox execution failed for user %s",
            current_user_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sandbox execution failed",
        ) from exc

from fastapi import APIRouter, Depends

from app.core.dependencies import get_app_name
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])

@router.get("/health", response_model=HealthResponse)
def health_check(
    app_name: str = Depends(get_app_name)
):
    return HealthResponse(
        status="healthy",
        application=app_name
    )
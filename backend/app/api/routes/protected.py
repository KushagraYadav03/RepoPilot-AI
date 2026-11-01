from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from app.core.jwt import verify_access_token
from app.core.dependencies import get_current_user_id
router = APIRouter(prefix="/protected", tags=["Protected"])


@router.get("/test")
def protected_test(
    user_id: int = Depends(get_current_user_id)
):
    return {
        "message": "Protected route accessed successfully",
        "user_id": user_id
    }
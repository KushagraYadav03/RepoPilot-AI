from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.jwt import verify_access_token
from app.db.session import SessionLocal


security = HTTPBearer()


def get_app_name() -> str:
    return "RepoPilot AI"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def resolve_user_id(current_user: Any) -> int:
    if isinstance(current_user, int):
        return current_user

    user_id = getattr(current_user, "id", None)

    if isinstance(user_id, int):
        return user_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authenticated user",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security)

) -> int:
    token = credentials.credentials
    user_id = verify_access_token(token)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return int(user_id)
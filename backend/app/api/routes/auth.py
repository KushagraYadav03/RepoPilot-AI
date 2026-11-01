
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user_id
from app.core.jwt import create_access_token
from app.core.security import hash_password, verify_password
from app.repositories.user import (
    create_user,
    get_user_by_email
)
from app.schemas.auth import UserLogin, UserRegister
from app.models.user import User

router = APIRouter(tags=["Authentication"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    user: UserRegister,
    db: Session = Depends(get_db)
):
    existing_user = get_user_by_email(db, user.email)

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    hashed_password = hash_password(user.password)

    new_user = create_user(
        db,
        name=user.name,
        email=user.email,
        hashed_password=hashed_password
    )

    return {
        "id": new_user.id,
        "name": new_user.name,
        "email": new_user.email
    }


@router.post("/login")
def login(
    user: UserLogin,
    db: Session = Depends(get_db)
):
    db_user = get_user_by_email(db, user.email)

    if not db_user or not verify_password(
        user.password,
        db_user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # Pass only the integer user ID
    access_token = create_access_token(db_user.id)

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@router.get("/users/me")
def read_current_user(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    current_user = db.get(User, user_id)

    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email
    }

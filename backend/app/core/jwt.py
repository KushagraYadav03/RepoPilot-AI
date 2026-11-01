
import os

from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from jwt.exceptions import InvalidTokenError

load_dotenv()

SECRET_KEY = os.environ["JWT_SECRET_KEY"]
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access"
    }

    token = jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return token


def verify_access_token(token: str):
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        # Temporary debugging
        print("JWT PAYLOAD:", payload)

        if payload.get("type") != "access":
            print("ERROR: Wrong token type")
            return None

        user_id = payload.get("sub")

        if not isinstance(user_id, str) or not user_id.isdigit():
            print("ERROR: Invalid user ID:", user_id)
            return None

        return int(user_id)

    except InvalidTokenError as error:
        print("JWT VERIFICATION ERROR:", repr(error))
        return None

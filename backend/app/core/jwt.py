import logging
import os

from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from jwt.exceptions import InvalidTokenError

load_dotenv()

logger = logging.getLogger(__name__)

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

        if payload.get("type") != "access":
            logger.warning("JWT verification failed: wrong token type")
            return None

        user_id = payload.get("sub")

        if not isinstance(user_id, str) or not user_id.isdigit():
            logger.warning("JWT verification failed: invalid user ID: %s", user_id)
            return None

        return int(user_id)

    except InvalidTokenError as error:
        logger.debug("JWT verification error: %s", repr(error))
        return None
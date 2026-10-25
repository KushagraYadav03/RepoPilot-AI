
import logging

from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.core.exceptions import (
    RepositoryNotFoundError,
    register_exception_handlers,
)
from app.core.dependencies import get_db

settings = get_settings()

setup_logging(settings.log_level)

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)

register_exception_handlers(app)


@app.get("/health")
def health():
    logger.info("Health endpoint called")

    return {
        "status": "healthy",
        "environment": settings.app_env,
    }


@app.get("/repositories/{repository_id}")
def get_repository(repository_id: int):
    raise RepositoryNotFoundError(repository_id)


@app.get("/db-health")
def database_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))

    return {
        "status": "success",
        "database": "connected",
    }

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
from app.api.routes.protected import router as protected_router
from app.api.routes.auth import router as auth_router

from app.api.routes.repositories import router as repositories_router

settings = get_settings()

setup_logging(settings.log_level)

logger = logging.getLogger(__name__)


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)
from app.api.routes.github import router as github_router

app.include_router (github_router)
app.include_router(repositories_router)

app.include_router(protected_router)
app.include_router(auth_router)
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
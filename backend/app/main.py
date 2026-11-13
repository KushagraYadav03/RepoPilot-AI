
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.core.exceptions import register_exception_handlers
from app.core.dependencies import get_db

from app.api.routes.protected import router as protected_router
from app.api.routes.auth import router as auth_router
from app.api.routes.repositories import router as repositories_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.github import router as github_router
from app.api.routes.retrieval import router as retrieval_router

from app.services.qdrant_service import close_local_qdrant_clients
from app.api.routes.chat import router as chat_router


settings = get_settings()

setup_logging(settings.log_level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("RepoPilot AI application starting")

    yield

    logger.info("Closing Qdrant clients")

    close_local_qdrant_clients()

    logger.info("RepoPilot AI application stopped")


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)


# ---------------------------------------------------------
# API ROUTERS
# ---------------------------------------------------------

app.include_router(auth_router)
app.include_router(protected_router)
app.include_router(repositories_router)
app.include_router(ingestion_router)
app.include_router(github_router)
app.include_router(retrieval_router)
app.include_router(chat_router)


# ---------------------------------------------------------
# EXCEPTION HANDLERS
# ---------------------------------------------------------

register_exception_handlers(app)


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@app.get("/health")
def health():

    logger.info("Health endpoint called")

    return {
        "status": "healthy",
        "application": settings.app_name,
    }


# ---------------------------------------------------------
# DATABASE HEALTH CHECK
# ---------------------------------------------------------

@app.get("/db-health")
def database_health(db: Session = Depends(get_db)):

    db.execute(text("SELECT 1"))

    return {
        "status": "success",
        "database": "connected",
    }

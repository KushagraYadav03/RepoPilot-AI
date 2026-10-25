import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class RepositoryNotFoundError(Exception):
    def __init__(self, repository_id: int):
        self.repository_id = repository_id


def register_exception_handlers(app: FastAPI):

    @app.exception_handler(RepositoryNotFoundError)
    async def repository_not_found(
        request: Request,
        exc: RepositoryNotFoundError
    ):
        logger.warning(
            "Repository not found: %s",
            exc.repository_id
        )

        return JSONResponse(
            status_code=404,
            content={
                "error": "REPOSITORY_NOT_FOUND",
                "message": "Repository does not exist"
            }
        )

    @app.exception_handler(Exception)
    async def unexpected_error(
        request: Request,
        exc: Exception
    ):
        logger.exception("Unexpected server error")

        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "message": "Something went wrong"
            }
        )
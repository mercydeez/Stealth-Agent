import logging
import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings


def _configure_logging() -> None:
    log_level = os.getenv("APP_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("app").setLevel(log_level)


_configure_logging()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Stealth Agent - headless job application automation",
    )
    app.include_router(api_router)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        logger = logging.getLogger(__name__)
        sanitized_errors = [
            error.get("msg", "Invalid request input.")
            for error in exc.errors()
        ]
        reason = "; ".join(sanitized_errors) or "Invalid request input."
        logger.warning("Request validation failed: %s", reason)
        return JSONResponse(
            status_code=400,
            content={
                "status": "failed",
                "fields_filled": [],
                "resume_uploaded": False,
                "questions_answered": [],
                "bot_blocked": False,
                "page_title": None,
                "step": "validation",
                "reason": reason,
            },
        )

    return app


app = create_app()

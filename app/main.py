import logging
import os

from fastapi import FastAPI

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
    return app


app = create_app()

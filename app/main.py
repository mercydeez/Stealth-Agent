from fastapi import FastAPI

from app.api import api_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Stealth Agent - headless job application automation",
    )
    app.include_router(api_router)
    return app


app = create_app()

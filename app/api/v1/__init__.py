from fastapi import APIRouter

from app.api.v1.apply import router as apply_router
from app.api.v1.health import router as health_router

router = APIRouter()
router.include_router(apply_router, tags=["applications"])
router.include_router(health_router, tags=["health"])

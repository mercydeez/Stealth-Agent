from fastapi import APIRouter

from app.api.v1.apply import router as apply_router

router = APIRouter()
router.include_router(apply_router, tags=["applications"])

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", summary="Health check")
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "stealth-agent",
    }

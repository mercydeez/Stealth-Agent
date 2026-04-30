from fastapi import APIRouter, status

from app.schemas.application import ApplicationRequest, ApplicationResponse
from app.services.application_service import ApplicationService

router = APIRouter()


@router.post(
    "/apply",
    response_model=ApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Accept a job application request",
)
async def apply_for_job(payload: ApplicationRequest) -> ApplicationResponse:
    return await ApplicationService.receive_application(payload)

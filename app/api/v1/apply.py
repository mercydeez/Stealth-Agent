from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.schemas.application import ApplicationRequest, ApplicationResponse
from app.services.application_service import ApplicationService

router = APIRouter()

SUCCESS_STATUSES = {"ready_to_submit", "submitted"}


def _failure_status_code(response: ApplicationResponse) -> int:
    reason = (response.reason or "").lower()
    step = (response.step or "").lower()

    if response.bot_blocked or step == "bot_blocked":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if step == "validation":
        return status.HTTP_400_BAD_REQUEST
    if step == "page_load":
        if "timed out" in reason:
            return status.HTTP_504_GATEWAY_TIMEOUT
        if "not found" in reason:
            return status.HTTP_404_NOT_FOUND
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_500_INTERNAL_SERVER_ERROR


@router.post(
    "/apply",
    response_model=ApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Accept a job application request",
)
async def apply_for_job(payload: ApplicationRequest) -> ApplicationResponse:
    response = await ApplicationService.receive_application(payload)
    if isinstance(response, dict):
        response = ApplicationResponse(**response)

    if response.status in SUCCESS_STATUSES:
        return response

    return JSONResponse(
        status_code=_failure_status_code(response),
        content=response.model_dump(),
    )

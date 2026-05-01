import asyncio
import logging
from functools import partial

from app.agent.browser import fill_application
from app.schemas.application import ApplicationRequest, ApplicationResponse

logger = logging.getLogger(__name__)


class ApplicationService:
    @staticmethod
    async def receive_application(payload: ApplicationRequest) -> ApplicationResponse:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                partial(
                    fill_application,
                    payload.job_url,
                    payload.applicant_data,
                    payload.resume_path,
                ),
            )
        except Exception:
            logger.exception("Unexpected application service failure")
            result = {
                "status": "failed",
                "step": "automation",
                "reason": "Unexpected automation failure.",
            }

        return ApplicationResponse(
            status=result.get("status", "unknown"),
            fields_filled=result.get("fields_filled", []),
            resume_uploaded=result.get("resume_uploaded", False),
            questions_answered=result.get("questions_answered", []),
            bot_blocked=result.get("bot_blocked", False),
            page_title=result.get("page_title"),
            step=result.get("step"),
            reason=result.get("reason"),
        )

from fastapi.testclient import TestClient

from app.main import app
from app.services.application_service import ApplicationService


client = TestClient(app)


def test_apply_endpoint_returns_browser_agent_response(monkeypatch) -> None:
    async def mock_receive_application(payload):
        return {
            "status": "ready_to_submit",
            "fields_filled": ["name", "email"],
        }

    monkeypatch.setattr(
        ApplicationService,
        "receive_application",
        mock_receive_application,
    )

    response = client.post(
        "/apply",
        json={
            "job_url": "https://example.com/jobs/backend-engineer",
            "applicant_data": "# Applicant\n\n- Name: Jane Doe",
            "resume_path": "C:/resumes/jane-doe.pdf",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready_to_submit",
        "fields_filled": ["name", "email"],
        "resume_uploaded": False,
        "questions_answered": [],
        "bot_blocked": False,
        "page_title": None,
        "step": None,
        "reason": None,
    }


def test_apply_endpoint_returns_structured_failure_response(monkeypatch) -> None:
    async def mock_receive_application(payload):
        return {
            "status": "failed",
            "fields_filled": ["name"],
            "resume_uploaded": False,
            "questions_answered": [],
            "bot_blocked": True,
            "page_title": "Security Check",
            "step": "bot_blocked",
            "reason": "Bot blocker detected: captcha",
        }

    monkeypatch.setattr(
        ApplicationService,
        "receive_application",
        mock_receive_application,
    )

    response = client.post(
        "/apply",
        json={
            "job_url": "https://example.com/jobs/backend-engineer",
            "applicant_data": "# Applicant\n\n- Name: Jane Doe",
            "resume_path": "C:/resumes/jane-doe.pdf",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "failed",
        "fields_filled": ["name"],
        "resume_uploaded": False,
        "questions_answered": [],
        "bot_blocked": True,
        "page_title": "Security Check",
        "step": "bot_blocked",
        "reason": "Bot blocker detected: captcha",
    }

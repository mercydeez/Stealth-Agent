from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app
from app.services.application_service import ApplicationService


client = TestClient(app)
FIXTURE_RESUME = Path(__file__).parent / "fixtures" / "resume.pdf"


def _payload(**overrides):
    payload = {
        "job_url": "https://jobs.lever.co/company/example-job",
        "applicant_data": "# Applicant\n\n- Name: Jane Doe",
        "resume_path": str(FIXTURE_RESUME),
    }
    payload.update(overrides)
    return payload


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "stealth-agent",
    }


def test_apply_endpoint_returns_success_response_contract(monkeypatch) -> None:
    async def mock_receive_application(payload):
        return {
            "status": "ready_to_submit",
            "fields_filled": ["name", "email"],
            "resume_uploaded": True,
            "questions_answered": [
                {
                    "question": "Why do you want to work here?",
                    "answer_preview": "I am excited about this role because...",
                }
            ],
            "bot_blocked": False,
            "page_title": "Example Job Posting",
            "step": None,
            "reason": None,
        }

    monkeypatch.setattr(ApplicationService, "receive_application", mock_receive_application)

    response = client.post("/apply", json=_payload())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready_to_submit",
        "fields_filled": ["name", "email"],
        "resume_uploaded": True,
        "questions_answered": [
            {
                "question": "Why do you want to work here?",
                "answer_preview": "I am excited about this role because...",
            }
        ],
        "bot_blocked": False,
        "page_title": "Example Job Posting",
        "step": None,
        "reason": None,
    }


def test_apply_endpoint_maps_job_not_found_to_404(monkeypatch) -> None:
    async def mock_receive_application(payload):
        return {
            "status": "failed",
            "step": "page_load",
            "reason": "Job posting not found or form not available",
        }

    monkeypatch.setattr(ApplicationService, "receive_application", mock_receive_application)

    response = client.post("/apply", json=_payload())

    assert response.status_code == 404
    assert response.json()["step"] == "page_load"


def test_apply_endpoint_maps_bot_block_to_503(monkeypatch) -> None:
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

    monkeypatch.setattr(ApplicationService, "receive_application", mock_receive_application)

    response = client.post("/apply", json=_payload())

    assert response.status_code == 503
    assert response.json()["bot_blocked"] is True


def test_apply_endpoint_maps_timeout_to_504(monkeypatch) -> None:
    async def mock_receive_application(payload):
        return {
            "status": "failed",
            "step": "page_load",
            "reason": "Form not found or page timed out",
        }

    monkeypatch.setattr(ApplicationService, "receive_application", mock_receive_application)

    response = client.post("/apply", json=_payload())

    assert response.status_code == 504
    assert response.json()["step"] == "page_load"


def test_apply_endpoint_maps_unexpected_automation_failure_to_500(monkeypatch) -> None:
    async def mock_receive_application(payload):
        return {
            "status": "failed",
            "step": "automation",
            "reason": "Unexpected automation failure.",
        }

    monkeypatch.setattr(ApplicationService, "receive_application", mock_receive_application)

    response = client.post("/apply", json=_payload())

    assert response.status_code == 500
    assert response.json()["reason"] == "Unexpected automation failure."


def test_missing_applicant_data_returns_400() -> None:
    payload = _payload()
    payload.pop("applicant_data")

    response = client.post("/apply", json=payload)

    assert response.status_code == 400
    assert response.json()["step"] == "validation"


def test_invalid_resume_path_returns_400() -> None:
    payload = _payload(resume_path=str(Path(__file__).parent / "fixtures" / "missing.pdf"))

    response = client.post("/apply", json=payload)

    assert response.status_code == 400
    assert response.json()["step"] == "validation"


def test_non_lever_url_returns_400() -> None:
    response = client.post(
        "/apply",
        json=_payload(job_url="https://example.com/jobs/backend-engineer"),
    )

    assert response.status_code == 400
    assert response.json()["step"] == "validation"

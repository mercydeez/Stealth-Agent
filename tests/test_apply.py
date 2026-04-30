from fastapi.testclient import TestClient

from app.main import app
from app.services.application_service import ApplicationService


client = TestClient(app)


def test_apply_endpoint_returns_browser_agent_response(monkeypatch) -> None:
    async def mock_receive_application(payload):
        return {
            "status": "fields_filled",
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
        "status": "fields_filled",
        "fields_filled": ["name", "email"],
    }

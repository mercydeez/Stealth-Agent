from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class ApplicationRequest(BaseModel):
    job_url: str = Field(..., description="The URL of the job posting.")
    applicant_data: str = Field(
        ...,
        description="Applicant information in markdown format.",
    )
    resume_path: str = Field(
        ...,
        description="Local path to the applicant's PDF resume.",
    )

    @field_validator("job_url")
    @classmethod
    def validate_job_url(cls, value: str) -> str:
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("job_url must be a valid http or https URL.")

        hostname = (parsed.hostname or "").lower()
        if hostname != "jobs.lever.co":
            raise ValueError("Unsupported ATS: only Lever-hosted job URLs are supported.")

        return url

    @field_validator("applicant_data")
    @classmethod
    def validate_applicant_data(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("applicant_data must not be empty.")
        return value

    @field_validator("resume_path")
    @classmethod
    def validate_resume_path(cls, value: str) -> str:
        resume_path = value.strip()
        if not resume_path:
            raise ValueError("resume_path must not be empty.")

        path = Path(resume_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError("resume_path must point to a PDF file.")
        if not path.is_file():
            raise ValueError("resume_path must point to an existing local PDF file.")

        return resume_path


class ApplicationResponse(BaseModel):
    status: str = Field(..., description="Processing status of the request.")
    fields_filled: list[str] = Field(
        default_factory=list,
        description="Applicant fields successfully filled on the job page.",
    )
    resume_uploaded: bool = Field(
        default=False,
        description="Whether a resume file was uploaded successfully.",
    )
    questions_answered: list[dict[str, str]] = Field(
        default_factory=list,
        description="Custom screening questions answered by the agent.",
    )
    bot_blocked: bool = Field(
        default=False,
        description="Whether the run appeared to hit anti-bot protection.",
    )
    page_title: str | None = Field(
        default=None,
        description="Title of the page that was processed.",
    )
    step: str | None = Field(
        default=None,
        description="Step where a failure occurred, if applicable.",
    )
    reason: str | None = Field(
        default=None,
        description="Failure reason, if applicable.",
    )

from pydantic import BaseModel, Field


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

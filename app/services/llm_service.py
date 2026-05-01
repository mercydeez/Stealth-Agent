import logging

from groq import Groq

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    pass


class LLMGenerationError(RuntimeError):
    pass


def generate_screening_answer(question: str, applicant_profile: str) -> str:
    if not settings.groq_api_key:
        raise LLMConfigurationError("GROQ_API_KEY is not configured.")

    prompt = (
        "You are helping draft a concise job application screening answer. "
        "Use only the applicant information provided. Do not invent employers, "
        "degrees, or achievements. Keep the answer professional and specific. "
        "Write 80-150 words.\n\n"
        f"Question: {question}\n\n"
        f"Applicant profile: {applicant_profile}"
    )

    try:
        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {
                    "role": "system",
                    "content": "Draft safe, concise job application screening answers.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
        answer = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("LLM answer generation failed: %s", exc)
        raise LLMGenerationError("LLM answer generation failed.") from exc

    if not answer:
        raise LLMGenerationError("LLM returned an empty answer.")

    return answer

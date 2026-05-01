import concurrent.futures
import logging
import re

from groq import Groq

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    pass


SALARY_ANSWER = (
    "Open to discussion based on the role, responsibilities, and overall compensation package."
)
FALLBACK_ANSWER = (
    "I am interested in this opportunity because it aligns with my skills, learning goals, and "
    "motivation to contribute meaningfully to the team."
)

SALARY_PHRASES = (
    "expected compensation",
    "desired salary",
    "salary expectation",
    "expected salary",
    "hourly rate",
    "pay rate",
)
SALARY_WORDS = ("salary", "compensation", "pay", "rate")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def is_salary_question(question: str) -> bool:
    if not question or not question.strip():
        return False

    normalized = _normalize_text(question)
    if any(phrase in normalized for phrase in SALARY_PHRASES):
        return True

    return any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in SALARY_WORDS)


def _request_groq_answer(prompt: str) -> str:
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
    return (response.choices[0].message.content or "").strip()


def _request_groq_answer_with_timeout(prompt: str, timeout_seconds: int) -> str:
    timeout_seconds = max(1, timeout_seconds)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_request_groq_answer, prompt)
        return future.result(timeout=timeout_seconds)


def generate_screening_answer(question: str, applicant_profile: str) -> str:
    if is_salary_question(question):
        logger.info("Salary question detected; using deterministic answer")
        return SALARY_ANSWER

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
        answer = _request_groq_answer_with_timeout(prompt, settings.groq_timeout_seconds)
    except (concurrent.futures.TimeoutError, Exception) as exc:
        logger.warning("LLM timeout/failure occurred: %s", exc)
        logger.info("Using fallback answer for screening question")
        return FALLBACK_ANSWER

    if not answer:
        logger.warning("LLM returned an empty answer; using fallback answer")
        return FALLBACK_ANSWER

    return answer

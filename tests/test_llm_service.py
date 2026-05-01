import concurrent.futures

from app.services import llm_service


class _FakeGroqResponse:
    class _Choice:
        class _Message:
            content = "I am excited about this role because it matches my background."

        message = _Message()

    choices = [_Choice()]


class _FakeCompletions:
    def create(self, **kwargs):
        return _FakeGroqResponse()


class _FakeChat:
    completions = _FakeCompletions()


class _FakeGroq:
    def __init__(self, api_key):
        self.api_key = api_key
        self.chat = _FakeChat()


def test_generate_screening_answer_can_be_mocked(monkeypatch) -> None:
    monkeypatch.setattr(llm_service.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(llm_service, "Groq", _FakeGroq)

    answer = llm_service.generate_screening_answer(
        "Why do you want to work here?",
        "# Applicant\n\n- Name: Jane Doe",
    )

    assert "excited" in answer


def test_salary_questions_return_deterministic_answer(monkeypatch) -> None:
    monkeypatch.setattr(llm_service.settings, "groq_api_key", "test-key")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("Groq should not be called for salary questions")

    monkeypatch.setattr(llm_service, "_request_groq_answer_with_timeout", _fail_if_called)

    questions = [
        "What is your desired salary?",
        "Expected compensation?",
        "What hourly rate are you looking for?",
    ]

    for question in questions:
        answer = llm_service.generate_screening_answer(question, "# Applicant\n\n- Name: Jane Doe")
        assert answer == llm_service.SALARY_ANSWER


def test_generate_screening_answer_timeout_fallback(monkeypatch) -> None:
    monkeypatch.setattr(llm_service.settings, "groq_api_key", "test-key")

    def _raise_timeout(*args, **kwargs):
        raise concurrent.futures.TimeoutError()

    monkeypatch.setattr(llm_service, "_request_groq_answer_with_timeout", _raise_timeout)

    answer = llm_service.generate_screening_answer(
        "Why do you want to work here?",
        "# Applicant\n\n- Name: Jane Doe",
    )

    assert answer == llm_service.FALLBACK_ANSWER

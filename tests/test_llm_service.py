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

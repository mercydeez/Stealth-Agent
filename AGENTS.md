# AGENTS.md

This is a Python/FastAPI project for a local Playwright-based Lever application demo agent.

- Run tests with `pytest` or `.venv\Scripts\pytest.exe` on Windows.
- Do not call the real Groq API in tests; mock `app.services.llm_service.generate_screening_answer` or `Groq`.
- Do not click the final Submit Application button by default.
- Do not implement CAPTCHA bypass, proxy rotation, credential evasion, or aggressive anti-bot evasion.
- Keep the public `POST /apply` request and response contract stable.

# Stealth Agent

Stealth Agent is a local FastAPI service that controls a Playwright-based Lever application micro-agent. It accepts a Lever job URL, applicant markdown data, and a local PDF resume path, fills the application form, uploads the resume, answers at least one open-ended screening question using Groq, and stops before the final Submit Application click.

## Safety Note

This project is intended for authorized testing and assignment demonstration only. By default, the agent stops at the final pre-submit state and does not click the final Submit Application button. Actual submission should only be enabled for verified dummy or test postings.

The agent includes lightweight browser compatibility and bot-block detection. It does not attempt to bypass strong anti-automation systems.

## Assignment Requirements Coverage

| Requirement | Implementation |
|---|---|
| Local REST API | FastAPI exposes POST /apply |
| Target job URL payload | job_url is accepted in the request body |
| Applicant data ingestion | applicant_data markdown is parsed and used to fill fields |
| Resume upload | resume_path points to a local PDF uploaded through the Lever form |
| Lever automation | Playwright navigates Lever-hosted application forms |
| LLM screening answers | Open-ended textarea questions are detected and answered using Groq |
| Error handling | API returns structured error responses with appropriate HTTP status codes |
| Bot-block detection | Bot-block-like states are detected and mapped to 503 |
| Execution state | Agent stops before final submit by default |
| Demo support | Set BROWSER_HEADLESS=false to show the browser during recording |

## Design Choices

- `FastAPI` provides a small local REST wrapper around the browser agent.
- `Playwright` controls Chromium and handles dynamic Lever DOM behavior.
- `Groq` generates concise screening-question answers from the provided applicant profile.
- `Pydantic` validates request payloads and keeps response data structured.
- `app/agent/browser.py` owns browser automation, while `app/services/` owns parsing and LLM helper logic.
- The API maps internal automation outcomes to clear public JSON responses and HTTP status codes.

## Project Structure

- `app/api/v1/apply.py` - POST /apply endpoint and response status mapping
- `app/api/v1/health.py` - GET /health endpoint
- `app/services/application_service.py` - async wrapper around the browser worker
- `app/services/applicant_parser.py` - markdown applicant-data parser
- `app/services/llm_service.py` - Groq screening-answer generation
- `app/agent/browser.py` - Lever automation flow
- `app/schemas/application.py` - request and response models
- `app/core/config.py` - environment-backed settings
- `run.py` - local server entrypoint
- `tests/test_apply.py` - API behavior tests
- `tests/test_applicant_parser.py` - applicant parser unit tests
- `tests/test_llm_service.py` - mocked LLM service test
- `sample_payload.json` - sample POST /apply request body

## Requirements

- Python 3.12+
- `GROQ_API_KEY`
- Playwright Chromium

## Installation

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

On Linux, install browser system dependencies if needed:

```bash
playwright install --with-deps chromium
```

## Environment Variables

Configure `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
BROWSER_HEADLESS=true
APP_LOG_LEVEL=INFO
```

- `GROQ_API_KEY`: required for screening-answer generation
- `GROQ_MODEL`: Groq model used by the LLM helper
- `BROWSER_HEADLESS`: set to `false` when recording the demo
- `APP_LOG_LEVEL`: logging level for API and agent steps

## Running the Server

```bash
python run.py
```

The API runs at:

```text
http://127.0.0.1:8000
```

Health check:

```bash
curl "http://127.0.0.1:8000/health"
```

## API Contract

### POST /apply

Request body:

```json
{
  "job_url": "https://jobs.lever.co/company/example-job",
  "applicant_data": "# Applicant\n\n- Name: Jane Doe\n- Email: jane@example.com\n- Phone: +1 555 0101\n- LinkedIn: https://www.linkedin.com/in/janedoe\n- Location: Toronto, ON\n- Portfolio: https://github.com/janedoe",
  "resume_path": "C:/path/to/resume.pdf"
}
```

Success response (`200 OK`):

```json
{
  "status": "ready_to_submit",
  "fields_filled": ["name", "email", "phone", "linkedin_url", "location"],
  "resume_uploaded": true,
  "questions_answered": [
    {
      "question": "Why do you want to work here?",
      "answer_preview": "I am excited about this role because..."
    }
  ],
  "bot_blocked": false,
  "page_title": "Example Job Posting",
  "step": null,
  "reason": null
}
```

Failure status table:

| HTTP Status | When It Is Returned |
|---|---|
| 400 | Invalid request input, unsupported ATS URL, missing resume, or non-PDF resume |
| 404 | Job posting or Lever application form is unavailable |
| 503 | Bot-block, CAPTCHA-like, or anti-automation state is detected |
| 504 | Page navigation or form loading times out |
| 500 | Unexpected automation failure |

## Demo Request

The repo includes `sample_payload.json`.

macOS/Linux:

```bash
curl -X POST "http://127.0.0.1:8000/apply" \
  -H "Content-Type: application/json" \
  --data-binary "@sample_payload.json"
```

Windows PowerShell:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/apply" `
  -H "Content-Type: application/json" `
  --data-binary "@sample_payload.json"
```

Update `sample_payload.json` so `resume_path` points to a real local PDF before running the demo.

## Logging

Logs are written to the server console. Major browser steps include:

- `open_job_url`
- `detect_form`
- `fill_contact_fields`
- `upload_resume`
- `detect_questions`
- `generate_llm_answer`
- `inject_llm_answer`
- `ready_to_submit`

Failures include a clean `step`, `reason`, and `bot_blocked` flag in the API response. Secrets and stack traces are not exposed in public JSON responses.

## Tests

Run all tests:

```bash
pytest
```

Windows:

```powershell
.venv\Scripts\pytest.exe
```

Tests do not call real Lever pages, do not launch a real browser, and do not call the real Groq API.

## Known Limitations

- Tuned for Lever-hosted forms only
- Does not attempt to bypass strong anti-automation systems
- Open-ended question handling targets textarea-style fields first
- Live ATS DOMs may vary
- The agent intentionally stops before submit

## Troubleshooting

| Issue | Possible Cause | Fix |
|---|---|---|
| GROQ_API_KEY missing | .env not configured | Add a valid key to .env |
| Browser does not open | Playwright browser not installed | Run playwright install chromium |
| Resume upload fails | Invalid path or unsupported file | Use an absolute path to a local PDF |
| Job form not found | Posting closed or page structure changed | Try another Lever-hosted posting |
| Bot blocked response | ATS protection or abnormal browser state | Re-run in visible mode and inspect the page |
| Timeout | Slow network or page load | Increase timeout in config or retry |

## Demo Video Checklist

- Set `BROWSER_HEADLESS=false`
- Start server with `python run.py`
- Send `POST /apply` using Postman, cURL, or Thunder Client
- Show browser opening
- Show fields filled
- Show resume uploaded
- Show LLM answer inserted
- Show it stopping before submit
- Show final JSON response

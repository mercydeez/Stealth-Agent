# Stealth Agent

Stealth Agent is a local FastAPI service that drives a Playwright-based Lever application micro-agent. It accepts a job URL, applicant profile data, and a local resume path, then navigates to the application form, fills fields, uploads the resume, answers at least one open-ended question with an LLM, and stops immediately before the final submit.

## Design Choices

- `FastAPI` provides a simple local REST API wrapper around the browser agent.
- `Playwright` handles browser control and dynamic DOM interaction.
- `playwright-stealth` adds baseline anti-bot hardening.
- `Groq` is used as the LLM provider for open-ended question answers.
- The browser flow is kept modular in `app/agent/browser.py` so DOM and ATS logic stay separate from the API layer.
- The API returns structured success and failure payloads, with HTTP error codes for failures and bot-block conditions.

## Project Structure

- `app/api/v1/apply.py` - `/apply` endpoint and HTTP response mapping
- `app/services/application_service.py` - async service wrapper around the browser worker
- `app/agent/browser.py` - Lever automation logic
- `app/schemas/application.py` - request and response models
- `app/core/config.py` - environment-backed settings
- `run.py` - local server entrypoint
- `tests/test_apply.py` - API behavior tests

## Requirements

- Python 3.12+
- A valid `GROQ_API_KEY`
- Playwright browser dependencies installed locally

## Installation

1. Create and activate a virtual environment.
2. Install Python dependencies:

```powershell
pip install -r requirements.txt
```

3. Install Playwright Chromium:

```powershell
playwright install chromium
```

4. Create your env file:

```powershell
Copy-Item .env.example .env
```

## Environment Variables

Add these values to `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
BROWSER_HEADLESS=true
APP_LOG_LEVEL=INFO
```

- `GROQ_API_KEY`: required for generating answers to custom screening questions
- `BROWSER_HEADLESS`: set to `true` for headless execution or `false` for visible demo mode
- `APP_LOG_LEVEL`: controls API and agent logging verbosity

## Running the Server

Start the local API:

```powershell
python run.py
```

The service will listen on:

- `http://127.0.0.1:8000`

## API Contract

### `POST /apply`

Request body:

```json
{
  "job_url": "https://jobs.lever.co/company/example-job",
  "applicant_data": "# Applicant\n\n- Name: Jane Doe\n- Email: jane@example.com\n- Phone: +1 555 0101\n- LinkedIn: https://www.linkedin.com/in/janedoe\n- Location: Toronto, ON",
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

Failure response examples:

- `404` if the job posting or form is not available
- `503` if anti-bot protections appear to have blocked the run
- `504` if the target page times out
- `500` for unexpected automation failures

## Demo Request

Example cURL request:

```bash
curl -X POST "http://127.0.0.1:8000/apply" \
  -H "Content-Type: application/json" \
  -d "{\"job_url\":\"https://jobs.lever.co/company/example-job\",\"applicant_data\":\"# Applicant\n\n- Name: Jane Doe\",\"resume_path\":\"C:/path/to/resume.pdf\"}"
```

## Validation

Run tests locally:

```powershell
.venv\Scripts\pytest.exe
```

Current automated coverage validates:

- success response contract
- failure HTTP status behavior
- import and test setup stability

## Known Limitations

- The current implementation is tuned for Lever-hosted forms, not other ATS platforms.
- Bot mitigation is lightweight and practical, not bulletproof against stronger anti-automation systems.
- Open-ended question handling currently targets textarea-based questions first.
- Live ATS behavior can vary by posting, geography, and anti-bot state.

## Submission Notes

For the final assignment demo:

1. Set `BROWSER_HEADLESS=false` so the browser is visible.
2. Start the API with `python run.py`.
3. Send a `POST /apply` request from Postman, cURL, or Thunder Client.
4. Record the browser completing the application up to the final submit state.

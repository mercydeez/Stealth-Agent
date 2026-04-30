import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq
from playwright.sync_api import ElementHandle, Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

logger = logging.getLogger(__name__)
stealth = Stealth()

CHROME_WINDOWS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

VIEWPORT = {"width": 1366, "height": 768}

LEVER_FIELD_SELECTORS = {
    "name": 'input[name="name"]',
    "email": 'input[name="email"]',
    "phone": 'input[name="phone"]',
    "linkedin_url": 'input[name="urls[LinkedIn]"]',
}

RESUME_SELECTORS = [
    'input[type="file"]',
    'input[name="resume"]',
    '[class*="resume"] input',
]

MARKDOWN_FIELD_ALIASES = {
    "name": ["name", "full name"],
    "email": ["email", "e-mail"],
    "phone": ["phone", "mobile", "telephone"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin_url"],
    "location": ["location", "city"],
}

STANDARD_QUESTION_TERMS = {
    "name",
    "full name",
    "email",
    "e-mail",
    "phone",
    "mobile",
    "telephone",
    "location",
    "city",
    "linkedin",
    "linkedin url",
    "resume",
    "cv",
}


def parse_applicant_data(applicant_data: str) -> dict[str, str]:
    logger.info("Parsing applicant data markdown")
    parsed_data: dict[str, str] = {}

    for field_name, aliases in MARKDOWN_FIELD_ALIASES.items():
        parsed_data[field_name] = ""
        for alias in aliases:
            pattern = rf"^\s*[-*]?\s*\**{re.escape(alias)}\**\s*:\s*(.+?)\s*$"
            match = re.search(pattern, applicant_data, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                parsed_data[field_name] = match.group(1).strip()
                logger.info("Parsed applicant field: %s", field_name)
                break

        if not parsed_data[field_name]:
            logger.info("Applicant field not found in markdown: %s", field_name)

    return parsed_data


def _wait_for_form_or_apply_link(page: Page) -> bool:
    try:
        page.wait_for_selector("form", timeout=15000)
        page.wait_for_timeout(2000)
        logger.info("Application form detected on current page")
        return True
    except PlaywrightTimeoutError:
        logger.info("No form detected on current page after initial wait")

    apply_link = page.query_selector('a[href$="/apply"]')
    if apply_link is None:
        logger.warning("No application form or apply link found on page")
        return False

    apply_url = apply_link.get_attribute("href")
    if not apply_url:
        logger.warning("Apply link was found but did not contain a usable href")
        return False

    logger.info("Apply link found, navigating to application page: %s", apply_url)
    page.goto(apply_url, wait_until="domcontentloaded")
    page.wait_for_selector("form", timeout=15000)
    page.wait_for_timeout(2000)
    logger.info("Application form detected after navigating to apply page")
    return True


def _fill_lever_field(page: Page, field_name: str, selector: str, value: str) -> bool:
    if not value:
        logger.info("Skipping %s because no applicant value was provided", field_name)
        return False

    field = page.query_selector(selector)
    if field is None:
        logger.info("Field not found: %s using selector %s", field_name, selector)
        return False

    logger.info("Field found: %s using selector %s", field_name, selector)
    field.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    page.keyboard.type(value, delay=100)
    logger.info("Field filled: %s", field_name)
    return True


def _confirm_resume_upload(file_input: ElementHandle, filename: str) -> bool:
    try:
        input_value = file_input.input_value()
        if filename.lower() in input_value.lower():
            return True
    except Exception:
        logger.info("Could not read file input value while confirming resume upload")

    try:
        nearby_text = file_input.evaluate(
            """element => {
                const pieces = [];
                const parentText = element.parentElement?.innerText || "";
                const grandParentText = element.parentElement?.parentElement?.innerText || "";
                const nextText = element.nextElementSibling?.innerText || "";
                if (parentText) pieces.push(parentText);
                if (grandParentText) pieces.push(grandParentText);
                if (nextText) pieces.push(nextText);
                return pieces.join(" ");
            }"""
        )
        return filename.lower() in nearby_text.lower()
    except Exception:
        logger.info("Could not inspect nearby upload area text")
        return False


def _upload_resume(page: Page, resume_path: str) -> bool:
    for selector in RESUME_SELECTORS:
        file_input = page.query_selector(selector)
        if file_input is None:
            logger.info("Resume upload field not found using selector %s", selector)
            continue

        filename = Path(resume_path).name

        try:
            logger.info("Resume upload field found using selector %s", selector)
            file_input.set_input_files(resume_path)
            page.wait_for_timeout(2000)
        except Exception as exc:
            logger.warning("Resume upload failed for %s: %s", filename, exc)
            return False

        if _confirm_resume_upload(file_input, filename):
            logger.info("Resume uploaded successfully")
            return True

        logger.warning("Resume upload could not be confirmed: %s", filename)
        return False

    logger.warning("No resume upload field found")
    return False


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _is_standard_question(label: str) -> bool:
    normalized = _normalize_label(label)
    return any(term in normalized for term in STANDARD_QUESTION_TERMS)


def _get_textarea_label(textarea: ElementHandle) -> str:
    aria_label = textarea.get_attribute("aria-label")
    if aria_label and aria_label.strip():
        return aria_label.strip()

    label_info = textarea.evaluate(
        """element => {
            const id = element.getAttribute("id");
            if (id) {
                const explicitLabel = document.querySelector(`label[for="${id}"]`);
                if (explicitLabel && explicitLabel.innerText.trim()) {
                    return explicitLabel.innerText.trim();
                }
            }

            let sibling = element.previousElementSibling;
            while (sibling) {
                if (sibling.tagName.toLowerCase() === "label" && sibling.innerText.trim()) {
                    return sibling.innerText.trim();
                }
                sibling = sibling.previousElementSibling;
            }

            const parentText = element.parentElement?.innerText || "";
            return parentText.trim();
        }"""
    )
    return label_info.strip() if label_info else ""


def _generate_groq_answer(applicant_data: str, question_label: str) -> str | None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("GROQ_API_KEY is not set; skipping question answering")
        return None

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional job applicant. Answer job application "
                        "questions in 3-4 sentences. Be specific, confident, and authentic."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Applicant background: {applicant_data}\n\n"
                        f"Question: {question_label}\n\n"
                        "Provide a professional answer."
                    ),
                },
            ],
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("Failed to generate Groq answer for question '%s': %s", question_label, exc)
        return None


def _answer_custom_questions(page: Page, applicant_data: str) -> list[str]:
    questions_answered: list[str] = []
    textareas = page.query_selector_all("textarea")
    logger.info("Found %s textarea elements on the page", len(textareas))

    for textarea in textareas:
        question_label = _get_textarea_label(textarea)
        if not question_label:
            logger.info("Skipping textarea because no label could be determined")
            continue

        if _is_standard_question(question_label):
            logger.info("Skipping standard field textarea: %s", question_label)
            continue

        answer = _generate_groq_answer(applicant_data, question_label)
        if not answer:
            continue

        textarea.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(answer, delay=80)
        questions_answered.append(question_label)
        logger.info("Answered question: %s", question_label[:50])

    return questions_answered


def _scan_additional_fields(page: Page) -> None:
    logger.info("Scrolling to check for additional visible fields")
    page.mouse.wheel(0, 1200)
    page.wait_for_timeout(1000)

    additional_fields = page.evaluate(
        """() => {
            const elements = Array.from(document.querySelectorAll("input, textarea"));
            return elements
                .filter((element) => {
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return (
                        style.visibility !== "hidden" &&
                        style.display !== "none" &&
                        rect.width > 0 &&
                        rect.height > 0
                    );
                })
                .map((element) => ({
                    tag: element.tagName.toLowerCase(),
                    name: element.getAttribute("name") || "",
                    type: element.getAttribute("type") || "",
                    placeholder: element.getAttribute("placeholder") || "",
                }));
        }"""
    )

    logger.info("Visible input/textarea fields after scroll: %s", additional_fields)


def fill_application(job_url: str, applicant_data: str, resume_path: str) -> dict:
    logger.info("Starting browser application flow for URL: %s", job_url)
    logger.info("Resume path received: %s", resume_path)

    applicant = parse_applicant_data(applicant_data)
    fields_filled: list[str] = []

    with sync_playwright() as playwright:
        logger.info("Launching Chromium browser")
        browser = playwright.chromium.launch(headless=False)

        try:
            logger.info("Creating browser context with Chrome Windows user agent")
            context = browser.new_context(
                user_agent=CHROME_WINDOWS_USER_AGENT,
                viewport=VIEWPORT,
            )
            page = context.new_page()
            stealth.apply_stealth_sync(page)

            try:
                logger.info("Navigating to job URL")
                page.goto(job_url, wait_until="networkidle")
                if not _wait_for_form_or_apply_link(page):
                    raise PlaywrightTimeoutError("Form not found or apply link unavailable")
            except PlaywrightTimeoutError:
                page_title = page.title()
                logger.warning("Form not found or page timed out for title '%s'", page_title)
                return {
                    "status": "failed",
                    "step": "page_load",
                    "reason": "Form not found or page timed out",
                    "fields_filled": [],
                    "resume_uploaded": False,
                    "questions_answered": [],
                    "page_title": page_title,
                }

            page_title = page.title()
            logger.info("Page loaded successfully with title '%s'", page_title)

            is_dead_page = "404" in page_title.lower() or "not found" in page_title.lower()
            if is_dead_page:
                logger.warning("Job posting not found after form wait. title='%s'", page_title)
                return {
                    "status": "failed",
                    "step": "page_load",
                    "reason": "Job posting not found or form not available",
                    "fields_filled": [],
                    "resume_uploaded": False,
                    "questions_answered": [],
                    "page_title": page_title,
                }

            for field_name, selector in LEVER_FIELD_SELECTORS.items():
                was_filled = _fill_lever_field(
                    page=page,
                    field_name=field_name,
                    selector=selector,
                    value=applicant.get(field_name, ""),
                )
                if was_filled:
                    fields_filled.append(field_name)

            resume_uploaded = _upload_resume(page, resume_path)
            _scan_additional_fields(page)
            questions_answered = _answer_custom_questions(page, applicant_data)

            logger.info("Finished filling fields: %s", fields_filled)

            return {
                "status": "fields_filled",
                "fields_filled": fields_filled,
                "resume_uploaded": resume_uploaded,
                "questions_answered": questions_answered,
                "page_title": page_title,
            }
        finally:
            browser.close()

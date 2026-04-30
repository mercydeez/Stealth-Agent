import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq
from playwright.sync_api import ElementHandle, Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from app.core.config import settings

load_dotenv()

logger = logging.getLogger(__name__)
stealth = Stealth()
GROQ_MODEL = "llama-3.3-70b-versatile"

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

UPLOAD_BUTTON_SELECTORS = [
    '[class*="resume"] button',
    '[class*="upload"] button',
    'label[for*="resume"]',
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

MEANINGLESS_LABELS = {"", "*", "✱"}
BOT_BLOCKER_TERMS = (
    "verify you are human",
    "verify you're human",
    "captcha",
    "access denied",
    "unusual traffic",
    "security check",
    "cloudflare",
    "bot detection",
)


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


def _detect_bot_blocker(page: Page) -> str | None:
    try:
        page_text = page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        page_text = ""

    try:
        page_title = page.title()
    except Exception:
        page_title = ""

    combined_text = f"{page_title}\n{page_text}".lower()
    for term in BOT_BLOCKER_TERMS:
        if term in combined_text:
            return term
    return None


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


def _fill_location_field(page: Page, applicant_fields: dict[str, str]) -> bool:
    location_value = applicant_fields.get("location", "")
    if not location_value:
        logger.info("Skipping location because no applicant value was provided")
        return False

    location_input = page.query_selector("input[name='location']")
    if not location_input:
        location_input = page.query_selector("input[placeholder*='ocation']")
    if not location_input:
        logger.info("Field not found: location")
        return False

    location_input.click()
    page.wait_for_timeout(500)
    page.keyboard.type(location_value, delay=100)
    page.wait_for_timeout(1500)

    suggestion = page.query_selector(
        ".autocomplete-option, [class*='suggestion'], [class*='dropdown'] li"
    )
    if suggestion:
        suggestion.click()
        page.wait_for_timeout(500)
    else:
        page.keyboard.press("Enter")

    logger.info("Filled field: location")
    return True


def _get_select_label(select: ElementHandle) -> str:
    aria_label = select.get_attribute("aria-label")
    if aria_label and aria_label.strip():
        return aria_label.strip()

    label_text = select.evaluate(
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

            const fieldContainer = element.parentElement?.parentElement;
            const previousText = fieldContainer?.previousElementSibling?.innerText || "";
            if (previousText.trim()) {
                return previousText.trim();
            }

            const listItemText = fieldContainer?.closest('li')?.innerText || "";
            if (listItemText.trim()) {
                return listItemText.trim().split('\\n')[0];
            }

            const container = element.closest('.application-question, .form-group, [class*="question"], [class*="field"]');
            return container?.querySelector('label, p, span')?.innerText || "";
        }"""
    )
    return label_text.strip() if label_text else ""


def _is_meaningful_label(label: str) -> bool:
    normalized = _normalize_label(label)
    if normalized in MEANINGLESS_LABELS:
        return False

    alpha_numeric = re.sub(r"[^a-z0-9]+", "", normalized)
    return len(alpha_numeric) >= 3


def _pick_dropdown_option(applicant_data: str, label: str, option_texts: list[str]) -> str | None:
    api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("GROQ_API_KEY is not set; skipping dropdown selection for '%s'", label)
        return None

    prompt = f"""
Job application dropdown field.
Question/Label: {label}
Available options: {option_texts}
Applicant background: {applicant_data}

Reply with ONLY the exact text of the best option to select. Nothing else.
"""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Choose the single best dropdown option for a job application field.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("Failed to choose dropdown option for '%s': %s", label, exc)
        return None


def _fill_dropdown_fields(page: Page, applicant_data: str) -> None:
    selects = page.query_selector_all("select")
    logger.info("Found %s dropdown(s) on page", len(selects))

    for select in selects:
        label = _get_select_label(select)
        if not label or not _is_meaningful_label(label):
            logger.info("Skipping dropdown because no label could be determined")
            continue

        options = select.query_selector_all("option")
        option_texts = [option.inner_text().strip() for option in options]
        option_texts = [text for text in option_texts if text]

        if option_texts and option_texts[0].lower().startswith("select"):
            option_texts = option_texts[1:]

        if not option_texts:
            logger.info("Skipping dropdown '%s' because it has no usable options", label)
            continue

        selected_option = _pick_dropdown_option(applicant_data, label, option_texts)
        if not selected_option:
            continue

        matched_option = next(
            (option_text for option_text in option_texts if option_text.lower() == selected_option.lower()),
            None,
        )
        if not matched_option:
            logger.warning(
                "Groq suggested '%s' for dropdown '%s', but no exact option matched",
                selected_option,
                label,
            )
            continue

        try:
            select.select_option(label=matched_option)
            page.wait_for_timeout(800)
            logger.info("Selected dropdown '%s' with option '%s'", label, matched_option)
        except Exception as exc:
            logger.warning("Failed to select dropdown '%s': %s", label, exc)


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
    for selector in UPLOAD_BUTTON_SELECTORS:
        upload_button = page.query_selector(selector)
        if upload_button:
            try:
                upload_button.click()
                page.wait_for_timeout(1000)
                logger.info("Clicked visible resume upload control: %s", selector)
                break
            except Exception as exc:
                logger.info("Could not click upload control %s: %s", selector, exc)

    filename = Path(resume_path).name

    for selector in RESUME_SELECTORS:
        file_input = page.query_selector(selector)
        if file_input is None:
            logger.info("Resume upload field not found using selector %s", selector)
            continue

        try:
            logger.info("Resume upload field found using selector %s", selector)
            file_input.set_input_files(resume_path)
            page.wait_for_timeout(2000)
            page_content = page.content()
            if filename in page_content:
                logger.info("Resume upload confirmed: %s", filename)
                return True

            logger.warning("Resume set but filename not confirmed in page")
            return True
        except Exception as exc:
            logger.warning("Resume upload failed for %s: %s", filename, exc)
            return False

    logger.warning("No resume upload field found")
    return False


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _is_standard_question(label: str) -> bool:
    normalized = _normalize_label(label)
    normalized = normalized.rstrip(":* ").strip()
    return normalized in STANDARD_QUESTION_TERMS


def _get_textarea_label(page: Page, textarea: ElementHandle) -> str:
    try:
        # Method 1: aria-label
        label = textarea.get_attribute("aria-label") or ""
        if label.strip():
            return label.strip()

        # Method 2: placeholder
        label = textarea.get_attribute("placeholder") or ""
        if label.strip():
            return label.strip()

        # Method 3: id -> label[for=id]
        tid = textarea.get_attribute("id") or ""
        if tid:
            label_el = page.query_selector(f"label[for='{tid}']")
            if label_el:
                text = label_el.inner_text().strip()
                if text:
                    return text

        # Method 4: name attribute -> find matching label in page
        name = textarea.get_attribute("name") or ""
        if name:
            label_el = page.query_selector(f"label[for='{name}']")
            if label_el:
                text = label_el.inner_text().strip()
                if text:
                    return text

        # Method 5: Walk up DOM using inner_text of parent containers
        # Try up to 5 levels up
        label = page.evaluate(
            """
            (el) => {
                let node = el.parentElement;
                for (let i = 0; i < 5; i++) {
                    if (!node) break;
                    const labels = node.querySelectorAll('label, h4, h3, p, span, div.application-label, div[class*="label"]');
                    for (const l of labels) {
                        const txt = l.innerText.trim();
                        if (txt && txt.length > 3 && txt.length < 200) {
                            return txt;
                        }
                    }
                    node = node.parentElement;
                }
                return '';
            }
            """,
            textarea,
        )
        if label and label.strip():
            return label.strip()

        return ""
    except Exception as e:
        logger.warning(f"Could not get textarea label: {e}")
        return ""


def _generate_groq_answer(applicant_data: str, question_label: str) -> str | None:
    api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("GROQ_API_KEY is not set; skipping question answering")
        return None

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
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


def _answer_custom_questions(page: Page, applicant_data: str) -> list[dict[str, str]]:
    questions_answered: list[dict[str, str]] = []
    for scroll_position in [0.25, 0.5, 0.75, 1.0]:
        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {scroll_position})")
        page.wait_for_timeout(1000)

    # DEBUG - log everything found on page
    all_inputs = page.query_selector_all("input")
    all_textareas = page.query_selector_all("textarea")
    all_selects = page.query_selector_all("select")

    logger.info(f"DEBUG - Total inputs found: {len(all_inputs)}")
    logger.info(f"DEBUG - Total textareas found: {len(all_textareas)}")  
    logger.info(f"DEBUG - Total selects found: {len(all_selects)}")

    for i, inp in enumerate(all_inputs):
        name = inp.get_attribute("name") or ""
        placeholder = inp.get_attribute("placeholder") or ""
        input_type = inp.get_attribute("type") or ""
        logger.info(f"DEBUG input[{i}]: type={input_type} name={name} placeholder={placeholder}")

    for i, ta in enumerate(all_textareas):
        aria = ta.get_attribute("aria-label") or ""
        placeholder = ta.get_attribute("placeholder") or ""
        tid = ta.get_attribute("id") or ""
        logger.info(f"DEBUG textarea[{i}]: id={tid} aria-label={aria} placeholder={placeholder}")

    for i, sel in enumerate(all_selects):
        name = sel.get_attribute("name") or ""
        logger.info(f"DEBUG select[{i}]: name={name}")

    textareas = page.query_selector_all("textarea")
    logger.info("Found %s textarea(s)", len(textareas))

    for textarea in textareas:
        question_label = _get_textarea_label(page, textarea)
        if not question_label or not _is_meaningful_label(question_label):
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
        questions_answered.append(
            {
                "question": question_label,
                "answer_preview": answer[:100],
            }
        )
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
        browser = playwright.chromium.launch(headless=settings.browser_headless)

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
                bot_blocker_reason = _detect_bot_blocker(page)
                if bot_blocker_reason:
                    logger.warning("Bot blocker detected after initial navigation: %s", bot_blocker_reason)
                    return {
                        "status": "failed",
                        "step": "bot_blocked",
                        "reason": f"Bot blocker detected: {bot_blocker_reason}",
                        "fields_filled": [],
                        "resume_uploaded": False,
                        "questions_answered": [],
                        "bot_blocked": True,
                        "page_title": page.title(),
                    }

                if not _wait_for_form_or_apply_link(page):
                    bot_blocker_reason = _detect_bot_blocker(page)
                    if bot_blocker_reason:
                        logger.warning("Bot blocker detected while waiting for form: %s", bot_blocker_reason)
                        return {
                            "status": "failed",
                            "step": "bot_blocked",
                            "reason": f"Bot blocker detected: {bot_blocker_reason}",
                            "fields_filled": [],
                            "resume_uploaded": False,
                            "questions_answered": [],
                            "bot_blocked": True,
                            "page_title": page.title(),
                        }
                    raise PlaywrightTimeoutError("Form not found or apply link unavailable")
            except PlaywrightTimeoutError:
                page_title = page.title()
                bot_blocker_reason = _detect_bot_blocker(page)
                if bot_blocker_reason:
                    logger.warning("Bot blocker detected on timed out page '%s': %s", page_title, bot_blocker_reason)
                    return {
                        "status": "failed",
                        "step": "bot_blocked",
                        "reason": f"Bot blocker detected: {bot_blocker_reason}",
                        "fields_filled": [],
                        "resume_uploaded": False,
                        "questions_answered": [],
                        "bot_blocked": True,
                        "page_title": page_title,
                    }
                logger.warning("Form not found or page timed out for title '%s'", page_title)
                return {
                    "status": "failed",
                    "step": "page_load",
                    "reason": "Form not found or page timed out",
                    "fields_filled": [],
                    "resume_uploaded": False,
                    "questions_answered": [],
                    "bot_blocked": False,
                    "page_title": page_title,
                }

            page_title = page.title()
            logger.info("Page loaded successfully with title '%s'", page_title)
            page.wait_for_timeout(2000)

            bot_blocker_reason = _detect_bot_blocker(page)
            if bot_blocker_reason:
                logger.warning("Bot blocker detected after form load: %s", bot_blocker_reason)
                return {
                    "status": "failed",
                    "step": "bot_blocked",
                    "reason": f"Bot blocker detected: {bot_blocker_reason}",
                    "fields_filled": fields_filled,
                    "resume_uploaded": False,
                    "questions_answered": [],
                    "bot_blocked": True,
                    "page_title": page_title,
                }

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
                    "bot_blocked": False,
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
                page.wait_for_timeout(1000)

            location_filled = _fill_location_field(page, applicant)
            if location_filled:
                fields_filled.append("location")
            page.wait_for_timeout(1000)

            _fill_dropdown_fields(page, applicant_data)
            page.wait_for_timeout(1000)

            resume_uploaded = _upload_resume(page, resume_path)
            page.wait_for_timeout(1000)
            _scan_additional_fields(page)
            questions_answered = _answer_custom_questions(page, applicant_data)

            logger.info("Finished filling fields: %s", fields_filled)

            return {
                "status": "ready_to_submit",
                "fields_filled": fields_filled,
                "resume_uploaded": resume_uploaded,
                "questions_answered": questions_answered,
                "bot_blocked": False,
                "page_title": page_title,
            }
        finally:
            browser.close()

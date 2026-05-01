import logging
import re
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import ElementHandle, Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from app.core.config import settings
from app.services.applicant_parser import parse_applicant_data
from app.services.llm_service import (
    LLMConfigurationError,
    SALARY_ANSWER,
    generate_screening_answer,
    is_salary_question,
)

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
    "portfolio": 'input[name="urls[Portfolio]"], input[name="urls[portfolio]"]',
    "github": 'input[name="urls[GitHub]"], input[name="urls[Github]"], input[name="urls[github]"]',
    "website": 'input[name="urls[Website]"], input[name="urls[website]"]',
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

STANDARD_QUESTION_FIELD_KEYWORDS = {
    "name": ("name", "full name"),
    "email": ("email", "e-mail"),
    "phone": ("phone", "mobile", "telephone"),
    "location": ("location", "current location", "city"),
    "linkedin_url": ("linkedin", "linkedin url"),
    "portfolio": ("portfolio", "portfolio url"),
    "github": ("github", "github url", "git hub"),
    "website": ("website", "personal website", "site"),
}

MEANINGLESS_LABELS = {"", "*", "✱"}
BOT_BLOCKER_TERMS = (
    "verify you are human",
    "verify you're human",
    "captcha",
    "h-captcha",
    "hcaptcha",
    "recaptcha",
    "g-recaptcha",
    "access denied",
    "unusual traffic",
    "security check",
    "cloudflare",
    "challenge",
    "bot detection",
    "blocked",
)


def _looks_like_bot_block(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in BOT_BLOCKER_TERMS) or "intercepts pointer events" in normalized


def _wait_for_form_or_apply_link(page: Page) -> bool:
    try:
        page.wait_for_selector("form", timeout=settings.browser_timeout_ms)
        page.wait_for_timeout(2000)
        logger.info("Application form detected on current page")
        return True
    except PlaywrightTimeoutError:
        logger.info("No form detected on current page after initial wait")

    apply_link = page.query_selector('a[href$="/apply"], a:has-text("Apply"), button:has-text("Apply")')
    if apply_link is None:
        logger.warning("No application form or apply link found on page")
        return False

    apply_url = apply_link.get_attribute("href")
    logger.info("Apply control found; opening application form")
    if apply_url:
        logger.info("Apply control href: %s", apply_url)
    apply_link.click()
    page.wait_for_selector("form", timeout=settings.browser_timeout_ms)
    page.wait_for_timeout(2000)
    logger.info("Application form detected after navigating to apply page")
    return True


def _find_bot_block_text_term(combined_text: str) -> str | None:
    for term in BOT_BLOCKER_TERMS:
        if term == "challenge":
            if any(keyword in combined_text for keyword in ("cloudflare", "security check", "verify")):
                return term
            continue
        if term in combined_text:
            return term
    return None


def detect_bot_block_from_signals(
    *,
    page_title: str,
    page_text: str,
    captcha_visible: bool,
    challenge_visible: bool,
    form_usable: bool,
) -> str | None:
    combined_text = f"{page_title}\n{page_text}".lower()
    text_term = _find_bot_block_text_term(combined_text)
    if text_term:
        return f"text indicates bot block: {text_term}"

    if captcha_visible or challenge_visible:
        if not form_usable:
            return "challenge detected and form not usable"
        return "visible captcha/challenge element detected"

    return None


def detect_bot_block(page: Page) -> str | None:
    try:
        page_text = page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        page_text = ""

    try:
        page_title = page.title()
    except Exception:
        page_title = ""

    try:
        captcha_visible = bool(
            page.evaluate(
                """() => {
                    const selectors = [
                        '.h-captcha',
                        '#h-captcha',
                        'iframe[title*="hcaptcha"]',
                        'iframe[src*="hcaptcha"]',
                        'div.g-recaptcha',
                        'iframe[title*="recaptcha"]',
                        'iframe[src*="recaptcha"]',
                        'iframe[title*="captcha"]',
                        'iframe[src*="captcha"]',
                    ];
                    return selectors.some((selector) => {
                        const node = document.querySelector(selector);
                        if (!node) return false;
                        const style = window.getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        return style.visibility !== "hidden"
                            && style.display !== "none"
                            && rect.width > 0
                            && rect.height > 0;
                    });
                }"""
            )
        )
    except Exception:
        logger.info("Could not inspect DOM-based captcha selectors")
        captcha_visible = False

    try:
        challenge_visible = bool(
            page.evaluate(
                """() => {
                    const selectors = [
                        '#cf-challenge',
                        '#cf-challenge-running',
                        '.cf-challenge',
                        '#challenge-form',
                        'form[id*="challenge"]',
                        'div[id*="challenge"]',
                        'iframe[title*="challenge"]',
                        'iframe[src*="challenge"]',
                    ];
                    return selectors.some((selector) => {
                        const node = document.querySelector(selector);
                        if (!node) return false;
                        const style = window.getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        return style.visibility !== "hidden"
                            && style.display !== "none"
                            && rect.width > 0
                            && rect.height > 0;
                    });
                }"""
            )
        )
    except Exception:
        logger.info("Could not inspect DOM-based challenge selectors")
        challenge_visible = False

    try:
        form_usable = bool(
            page.evaluate(
                """() => {
                    const form = document.querySelector('form');
                    if (!form) return false;
                    const fields = Array.from(form.querySelectorAll('input, textarea, select'));
                    return fields.some((field) => {
                        const style = window.getComputedStyle(field);
                        const rect = field.getBoundingClientRect();
                        const ariaDisabled = field.getAttribute('aria-disabled');
                        return style.visibility !== 'hidden'
                            && style.display !== 'none'
                            && rect.width > 0
                            && rect.height > 0
                            && !field.disabled
                            && ariaDisabled !== 'true';
                    });
                }"""
            )
        )
    except Exception:
        form_usable = True

    return detect_bot_block_from_signals(
        page_title=page_title,
        page_text=page_text or "",
        captcha_visible=captcha_visible,
        challenge_visible=challenge_visible,
        form_usable=form_usable,
    )


def _is_visible_element(element: ElementHandle) -> bool:
    try:
        return bool(
            element.evaluate(
                """el => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== "hidden"
                        && style.display !== "none"
                        && rect.width > 0
                        && rect.height > 0
                        && !el.disabled;
                }"""
            )
        )
    except Exception:
        return False


def _failure_result(
    step: str,
    reason: str,
    *,
    page_title: str | None = None,
    fields_filled: list[str] | None = None,
    resume_uploaded: bool = False,
    questions_answered: list[dict[str, str]] | None = None,
    bot_blocked: bool = False,
) -> dict:
    logger.warning("[%s] %s", step, reason)
    return {
        "status": "failed",
        "fields_filled": fields_filled or [],
        "resume_uploaded": resume_uploaded,
        "questions_answered": questions_answered or [],
        "bot_blocked": bot_blocked,
        "page_title": page_title,
        "step": step,
        "reason": reason,
    }


def _fill_lever_field(page: Page, field_name: str, selector: str, value: str) -> bool:
    if not value:
        logger.info("Skipping %s because no applicant value was provided", field_name)
        return False

    field = page.query_selector(selector)
    if field is None:
        logger.info("Field not found: %s using selector %s", field_name, selector)
        return False
    if not _is_visible_element(field):
        logger.info("Skipping hidden or disabled field: %s", field_name)
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
    if not _is_visible_element(location_input):
        logger.info("Skipping hidden or disabled field: location")
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


SPONSORSHIP_LABEL_KEYWORDS = (
    "sponsorship",
    "work authorization",
    "work authorisation",
    "work permit",
    "eligible to work",
    "visa",
)
GENDER_LABEL_KEYWORDS = ("gender", "gender identity", "sex")
RACE_LABEL_KEYWORDS = ("race", "ethnicity")
VETERAN_LABEL_KEYWORDS = ("veteran", "military")
DISABILITY_LABEL_KEYWORDS = ("disability", "disabled")

DECLINE_KEYWORDS = (
    "prefer not",
    "decline",
    "do not wish",
    "do not want",
    "not disclose",
    "not to answer",
    "self-identify",
    "self identify",
)

SPONSORSHIP_NO_KEYWORDS = (
    "do not require sponsorship",
    "does not require sponsorship",
    "not require sponsorship",
    "no sponsorship",
    "no sponsorship required",
    "authorized to work",
    "authorised to work",
    "eligible to work",
    "not applicable",
)
SPONSORSHIP_YES_KEYWORDS = (
    "require sponsorship",
    "requires sponsorship",
    "needs sponsorship",
    "need sponsorship",
    "sponsorship required",
    "require visa",
    "requires visa",
    "will require sponsorship",
)

VETERAN_NO_KEYWORDS = (
    "not a veteran",
    "not veteran",
    "non-veteran",
    "no veteran",
    "i am not a veteran",
)

DISABILITY_NO_KEYWORDS = (
    "no disability",
    "not disabled",
    "do not have a disability",
    "i do not have a disability",
)


def _option_has_keywords(option: str, keywords: tuple[str, ...]) -> bool:
    normalized = _normalize_label(option)
    for keyword in keywords:
        if keyword in {"yes", "no"}:
            if re.search(rf"\b{re.escape(keyword)}\b", normalized):
                return True
        elif keyword in normalized:
            return True
    return False


def _find_option_by_keywords(option_texts: list[str], keywords: tuple[str, ...]) -> str | None:
    for option in option_texts:
        if _option_has_keywords(option, keywords):
            return option
    return None


def _match_option_by_value(option_texts: list[str], target_value: str) -> str | None:
    normalized_target = _normalize_label(target_value)
    if not normalized_target:
        return None

    for option in option_texts:
        normalized_option = _normalize_label(option)
        if re.search(rf"\b{re.escape(normalized_target)}\b", normalized_option):
            return option
    return None


def _applicant_requires_sponsorship(applicant_fields: dict[str, str]) -> bool | None:
    candidate_text = " ".join(
        filter(
            None,
            [
                applicant_fields.get("work_authorization", ""),
                applicant_fields.get("sponsorship", ""),
            ],
        )
    )
    normalized = _normalize_label(candidate_text)
    if not normalized:
        return None

    if any(phrase in normalized for phrase in SPONSORSHIP_YES_KEYWORDS):
        return True
    if any(phrase in normalized for phrase in SPONSORSHIP_NO_KEYWORDS):
        return False
    if "require" in normalized and "sponsorship" in normalized:
        return True
    if "no" in normalized and "sponsorship" in normalized:
        return False
    return None


def _select_sponsorship_option(
    option_texts: list[str], applicant_fields: dict[str, str]
) -> str | None:
    requires_sponsorship = _applicant_requires_sponsorship(applicant_fields)
    if requires_sponsorship is True:
        return _find_option_by_keywords(option_texts, SPONSORSHIP_YES_KEYWORDS) or _find_option_by_keywords(
            option_texts, ("yes",)
        )

    return (
        _find_option_by_keywords(option_texts, SPONSORSHIP_NO_KEYWORDS)
        or _find_option_by_keywords(option_texts, ("no",))
        or _find_option_by_keywords(option_texts, ("not applicable",))
    )


def _select_gender_option(option_texts: list[str], applicant_fields: dict[str, str]) -> str | None:
    explicit_gender = applicant_fields.get("gender", "")
    match = _match_option_by_value(option_texts, explicit_gender)
    if match:
        return match
    return _find_option_by_keywords(option_texts, DECLINE_KEYWORDS)


def _select_race_option(option_texts: list[str], applicant_fields: dict[str, str]) -> str | None:
    explicit_race = applicant_fields.get("race", "")
    match = _match_option_by_value(option_texts, explicit_race)
    if match:
        return match
    return _find_option_by_keywords(option_texts, DECLINE_KEYWORDS)


def _select_veteran_option(option_texts: list[str], applicant_fields: dict[str, str]) -> str | None:
    explicit_veteran = applicant_fields.get("veteran_status", "")
    if explicit_veteran:
        match = _match_option_by_value(option_texts, explicit_veteran)
        if match:
            return match

        normalized = _normalize_label(explicit_veteran)
        if "not" in normalized or "no" in normalized:
            return _find_option_by_keywords(option_texts, VETERAN_NO_KEYWORDS)
        if "veteran" in normalized:
            return _find_option_by_keywords(option_texts, ("veteran", "yes"))

    return _find_option_by_keywords(option_texts, VETERAN_NO_KEYWORDS) or _find_option_by_keywords(
        option_texts, DECLINE_KEYWORDS
    )


def _select_disability_option(option_texts: list[str], applicant_fields: dict[str, str]) -> str | None:
    explicit_disability = applicant_fields.get("disability_status", "")
    if explicit_disability:
        match = _match_option_by_value(option_texts, explicit_disability)
        if match:
            return match
        normalized = _normalize_label(explicit_disability)
        if "no" in normalized or "not" in normalized:
            return _find_option_by_keywords(option_texts, DISABILITY_NO_KEYWORDS) or _find_option_by_keywords(
                option_texts, ("no",)
            )
        if "yes" in normalized or "have" in normalized:
            return _find_option_by_keywords(option_texts, ("yes", "have a disability"))

    return _find_option_by_keywords(option_texts, DECLINE_KEYWORDS)


def select_dropdown_option(
    label: str, option_texts: list[str], applicant_fields: dict[str, str]
) -> str | None:
    normalized_label = _normalize_label(label)
    if not normalized_label:
        return None

    if any(keyword in normalized_label for keyword in SPONSORSHIP_LABEL_KEYWORDS):
        return _select_sponsorship_option(option_texts, applicant_fields)
    if any(keyword in normalized_label for keyword in GENDER_LABEL_KEYWORDS):
        return _select_gender_option(option_texts, applicant_fields)
    if any(keyword in normalized_label for keyword in RACE_LABEL_KEYWORDS):
        return _select_race_option(option_texts, applicant_fields)
    if any(keyword in normalized_label for keyword in VETERAN_LABEL_KEYWORDS):
        return _select_veteran_option(option_texts, applicant_fields)
    if any(keyword in normalized_label for keyword in DISABILITY_LABEL_KEYWORDS):
        return _select_disability_option(option_texts, applicant_fields)

    return None


def _fill_dropdown_fields(page: Page, applicant_fields: dict[str, str]) -> None:
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

        selected_option = select_dropdown_option(label, option_texts, applicant_fields)
        if not selected_option:
            logger.debug("Skipping dropdown '%s' because no deterministic option was selected", label)
            continue

        matched_option = next(
            (option_text for option_text in option_texts if option_text.lower() == selected_option.lower()),
            None,
        )
        if not matched_option:
            logger.warning(
                "Selected option '%s' for dropdown '%s' did not match an available option",
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


def _label_contains_keyword(normalized_label: str, keyword: str) -> bool:
    if " " in keyword:
        return keyword in normalized_label
    return bool(re.search(rf"\b{re.escape(keyword)}\b", normalized_label))


def _match_standard_field(question_label: str) -> str | None:
    normalized = _normalize_label(question_label).rstrip(":* ").strip()
    for field_name, keywords in STANDARD_QUESTION_FIELD_KEYWORDS.items():
        for keyword in keywords:
            if _label_contains_keyword(normalized, keyword):
                return field_name
    return None


def select_standard_answer(question_label: str, applicant_fields: dict[str, str]) -> tuple[str | None, str | None]:
    field_name = _match_standard_field(question_label)
    if not field_name:
        return None, None

    value = (applicant_fields.get(field_name) or "").strip()
    if not value:
        return None, field_name

    return value, field_name


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


def _generate_groq_answer(applicant_data: str, question_label: str) -> str:
    return generate_screening_answer(question_label, applicant_data)


def _answer_custom_questions(
    page: Page, applicant_data: str, applicant_fields: dict[str, str]
) -> list[dict[str, str]]:
    questions_answered: list[dict[str, str]] = []
    llm_used = False
    for scroll_position in [0.25, 0.5, 0.75, 1.0]:
        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {scroll_position})")
        page.wait_for_timeout(1000)

    # DEBUG - log everything found on page
    all_inputs = page.query_selector_all("input")
    all_textareas = page.query_selector_all("textarea")
    all_selects = page.query_selector_all("select")

    logger.debug("Total inputs found: %s", len(all_inputs))
    logger.debug("Total textareas found: %s", len(all_textareas))
    logger.debug("Total selects found: %s", len(all_selects))

    for i, inp in enumerate(all_inputs):
        name = inp.get_attribute("name") or ""
        placeholder = inp.get_attribute("placeholder") or ""
        input_type = inp.get_attribute("type") or ""
        logger.debug("input[%s]: type=%s name=%s placeholder=%s", i, input_type, name, placeholder)

    for i, ta in enumerate(all_textareas):
        aria = ta.get_attribute("aria-label") or ""
        placeholder = ta.get_attribute("placeholder") or ""
        tid = ta.get_attribute("id") or ""
        logger.debug("textarea[%s]: id=%s aria-label=%s placeholder=%s", i, tid, aria, placeholder)

    for i, sel in enumerate(all_selects):
        name = sel.get_attribute("name") or ""
        logger.debug("select[%s]: name=%s", i, name)

    textareas = page.query_selector_all("textarea")
    logger.info("Found %s textarea(s)", len(textareas))

    for textarea in textareas:
        if not _is_visible_element(textarea):
            logger.info("Skipping hidden or disabled textarea")
            continue

        question_label = _get_textarea_label(page, textarea)
        if not question_label or not _is_meaningful_label(question_label):
            logger.info("Skipping textarea because no label could be determined")
            continue

        standard_answer, standard_field = select_standard_answer(question_label, applicant_fields)
        if standard_field:
            if standard_answer:
                logger.info(
                    "Using applicant %s for standard question: %s",
                    standard_field,
                    question_label[:80],
                )
                answer = standard_answer
            else:
                logger.info("Skipping standard question with no applicant value: %s", question_label)
                continue
        elif is_salary_question(question_label):
            logger.info("Using deterministic salary answer for question: %s", question_label[:80])
            answer = SALARY_ANSWER
        else:
            if llm_used:
                logger.info("Skipping additional open-ended question after LLM answer: %s", question_label[:80])
                continue
            logger.info("[generate_llm_answer] Generating answer for question: %s", question_label[:80])
            answer = _generate_groq_answer(applicant_data, question_label)
            llm_used = True
        logger.info("[inject_llm_answer] Inserting generated answer into textarea")
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


def _has_submit_button(page: Page) -> bool:
    submit_button = page.query_selector(
        'button[type="submit"], input[type="submit"], button:has-text("Submit Application"), button:has-text("Submit")'
    )
    return bool(submit_button and _is_visible_element(submit_button))


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

    logger.debug("Visible input/textarea fields after scroll: %s", additional_fields)


def fill_application(job_url: str, applicant_data: str, resume_path: str) -> dict:
    logger.info("Starting browser application flow for URL: %s", job_url)
    logger.info("Resume path received: %s", resume_path)

    page_title: str | None = None
    applicant = parse_applicant_data(applicant_data)
    fields_filled: list[str] = []
    resume_uploaded = False
    questions_answered: list[dict[str, str]] = []
    browser = None

    try:
        with sync_playwright() as playwright:
            logger.info("[open_job_url] Launching Chromium browser")
            browser = playwright.chromium.launch(headless=settings.browser_headless)

            logger.info("Creating browser context with Chrome Windows user agent")
            context = browser.new_context(
                user_agent=CHROME_WINDOWS_USER_AGENT,
                viewport=VIEWPORT,
            )
            page = context.new_page()
            stealth.apply_stealth_sync(page)

            try:
                logger.info("[open_job_url] Navigating to job URL")
                page.goto(job_url, wait_until="networkidle", timeout=settings.browser_timeout_ms)
                bot_blocker_reason = detect_bot_block(page)
                if bot_blocker_reason:
                    return _failure_result(
                        "bot_blocked",
                        f"Bot blocker detected: {bot_blocker_reason}",
                        page_title=page.title(),
                        bot_blocked=True,
                    )

                logger.info("[detect_form] Looking for application form")
                if not _wait_for_form_or_apply_link(page):
                    bot_blocker_reason = detect_bot_block(page)
                    if bot_blocker_reason:
                        return _failure_result(
                            "bot_blocked",
                            f"Bot blocker detected: {bot_blocker_reason}",
                            page_title=page.title(),
                            bot_blocked=True,
                        )
                    raise PlaywrightTimeoutError("Form not found or apply link unavailable")
            except PlaywrightTimeoutError as exc:
                if _looks_like_bot_block(str(exc)):
                    return _failure_result(
                        "bot_blocked",
                        "Bot blocker detected while loading the application form.",
                        page_title=page.title(),
                        bot_blocked=True,
                    )
                page_title = page.title()
                bot_blocker_reason = detect_bot_block(page)
                if bot_blocker_reason:
                    return _failure_result(
                        "bot_blocked",
                        f"Bot blocker detected: {bot_blocker_reason}",
                        page_title=page_title,
                        bot_blocked=True,
                    )
                return _failure_result(
                    "page_load",
                    "Form not found or page timed out",
                    page_title=page_title,
                )

            page_title = page.title()
            logger.info("Page loaded successfully with title '%s'", page_title)
            page.wait_for_timeout(2000)

            bot_blocker_reason = detect_bot_block(page)
            if bot_blocker_reason:
                return _failure_result(
                    "bot_blocked",
                    f"Bot blocker detected: {bot_blocker_reason}",
                    page_title=page_title,
                    fields_filled=fields_filled,
                    bot_blocked=True,
                )

            is_dead_page = "404" in page_title.lower() or "not found" in page_title.lower()
            if is_dead_page:
                return _failure_result(
                    "page_load",
                    "Job posting not found or form not available",
                    page_title=page_title,
                )

            logger.info("[fill_contact_fields] Filling standard applicant fields")
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

            _fill_dropdown_fields(page, applicant)
            page.wait_for_timeout(1000)

            logger.info("[upload_resume] Uploading resume")
            resume_uploaded = _upload_resume(page, resume_path)
            if not resume_uploaded:
                return _failure_result(
                    "upload_resume",
                    "Resume upload failed or upload field was unavailable",
                    page_title=page_title,
                    fields_filled=fields_filled,
                )
            page.wait_for_timeout(1000)

            _scan_additional_fields(page)
            logger.info("[detect_questions] Looking for open-ended screening questions")
            try:
                questions_answered = _answer_custom_questions(page, applicant_data, applicant)
            except LLMConfigurationError as exc:
                return _failure_result(
                    "generate_llm_answer",
                    str(exc),
                    page_title=page_title,
                    fields_filled=fields_filled,
                    resume_uploaded=resume_uploaded,
                )
            except PlaywrightTimeoutError as exc:
                if _looks_like_bot_block(str(exc)):
                    return _failure_result(
                        "bot_blocked",
                        "Bot blocker detected while interacting with a screening question field.",
                        page_title=page_title,
                        fields_filled=fields_filled,
                        resume_uploaded=resume_uploaded,
                        questions_answered=questions_answered,
                        bot_blocked=True,
                    )
                bot_blocker_reason = detect_bot_block(page)
                if bot_blocker_reason:
                    return _failure_result(
                        "bot_blocked",
                        f"Bot blocker detected: {bot_blocker_reason}",
                        page_title=page_title,
                        fields_filled=fields_filled,
                        resume_uploaded=resume_uploaded,
                        questions_answered=questions_answered,
                        bot_blocked=True,
                    )
                return _failure_result(
                    "inject_llm_answer",
                    "Timed out while interacting with a screening question field.",
                    page_title=page_title,
                    fields_filled=fields_filled,
                    resume_uploaded=resume_uploaded,
                    questions_answered=questions_answered,
                )

            if not questions_answered:
                return _failure_result(
                    "detect_questions",
                    "No open-ended textarea screening question could be answered",
                    page_title=page_title,
                    fields_filled=fields_filled,
                    resume_uploaded=resume_uploaded,
                )

            if _has_submit_button(page):
                logger.info("[ready_to_submit] Submit button detected; stopping before final submit")
            else:
                logger.info("[ready_to_submit] Form filled; no visible submit button detected")

            logger.info("Finished filling fields: %s", fields_filled)

            return {
                "status": "ready_to_submit",
                "fields_filled": fields_filled,
                "resume_uploaded": resume_uploaded,
                "questions_answered": questions_answered,
                "bot_blocked": False,
                "page_title": page_title,
            }
    except Exception:
        logger.exception("Unexpected browser automation failure")
        return _failure_result(
            "automation",
            "Unexpected automation failure.",
            page_title=page_title,
            fields_filled=fields_filled,
            resume_uploaded=resume_uploaded,
            questions_answered=questions_answered,
        )
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                logger.info("Browser was already closed during shutdown")

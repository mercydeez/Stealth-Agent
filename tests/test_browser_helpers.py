from app.agent.browser import (
    detect_bot_block_from_signals,
    select_dropdown_option,
    select_standard_answer,
)


def test_select_dropdown_option_sponsorship_defaults_to_no() -> None:
    applicant_fields = {
        "work_authorization": "Does not require sponsorship",
        "sponsorship": "",
    }
    options = ["Yes", "No", "I do not require sponsorship"]

    selected = select_dropdown_option("Do you require sponsorship?", options, applicant_fields)

    assert selected == "I do not require sponsorship"


def test_select_dropdown_option_sponsorship_requires_yes() -> None:
    applicant_fields = {
        "work_authorization": "Requires sponsorship",
        "sponsorship": "",
    }
    options = ["Yes", "No"]

    selected = select_dropdown_option("Work authorization / sponsorship", options, applicant_fields)

    assert selected == "Yes"


def test_select_dropdown_option_gender_declines_when_unknown() -> None:
    options = ["Female", "Male", "Prefer not to say"]

    selected = select_dropdown_option("Gender", options, {})

    assert selected == "Prefer not to say"


def test_select_dropdown_option_race_matches_explicit() -> None:
    applicant_fields = {"race": "Asian"}
    options = ["White", "Asian", "Prefer not to say"]

    selected = select_dropdown_option("Race", options, applicant_fields)

    assert selected == "Asian"


def test_select_dropdown_option_veteran_prefers_not_veteran() -> None:
    options = ["I am not a veteran", "I am a protected veteran", "Prefer not to say"]

    selected = select_dropdown_option("Veteran status", options, {})

    assert selected == "I am not a veteran"


def test_select_dropdown_option_disability_declines_when_unknown() -> None:
    options = [
        "Yes, I have a disability",
        "No, I do not have a disability",
        "Prefer not to answer",
    ]

    selected = select_dropdown_option("Disability status", options, {})

    assert selected == "Prefer not to answer"


def test_select_standard_answer_location_question() -> None:
    applicant_fields = {"location": "Toronto, ON"}

    answer, field = select_standard_answer("What is your current location?", applicant_fields)

    assert field == "location"
    assert answer == "Toronto, ON"


def test_detect_bot_block_from_text_signal() -> None:
    reason = detect_bot_block_from_signals(
        page_title="Security Check",
        page_text="Verify you are human to continue.",
        captcha_visible=False,
        challenge_visible=False,
        form_usable=True,
    )

    assert reason is not None
    assert "text indicates" in reason


def test_detect_bot_block_from_visible_captcha() -> None:
    reason = detect_bot_block_from_signals(
        page_title="",
        page_text="",
        captcha_visible=True,
        challenge_visible=False,
        form_usable=True,
    )

    assert reason is not None
    assert "captcha" in reason


def test_detect_bot_block_returns_none_when_clear() -> None:
    reason = detect_bot_block_from_signals(
        page_title="Job Application",
        page_text="Apply now for this role.",
        captcha_visible=False,
        challenge_visible=False,
        form_usable=True,
    )

    assert reason is None

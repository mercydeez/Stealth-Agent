from app.services.applicant_parser import parse_applicant_data


def test_parse_applicant_data_extracts_common_markdown_fields() -> None:
    applicant_data = """
# Applicant

- Name: Jane Doe
Email: jane@example.com
**Phone:** +1 555 0101
LinkedIn URL: https://www.linkedin.com/in/janedoe
Portfolio: https://portfolio.example.com
GitHub: https://github.com/janedoe
Website: https://janedoe.dev
Location: Toronto, ON
"""

    parsed = parse_applicant_data(applicant_data)

    assert parsed["name"] == "Jane Doe"
    assert parsed["email"] == "jane@example.com"
    assert parsed["phone"] == "+1 555 0101"
    assert parsed["linkedin_url"] == "https://www.linkedin.com/in/janedoe"
    assert parsed["portfolio"] == "https://portfolio.example.com"
    assert parsed["github"] == "https://github.com/janedoe"
    assert parsed["website"] == "https://janedoe.dev"
    assert parsed["location"] == "Toronto, ON"

import re


APPLICANT_FIELD_ALIASES = {
    "name": ["name", "full name"],
    "email": ["email", "e-mail"],
    "phone": ["phone", "mobile", "telephone"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin_url"],
    "portfolio": ["portfolio", "portfolio url"],
    "github": ["github", "github url", "git hub"],
    "website": ["website", "personal website", "site"],
    "location": ["location", "city"],
}


def parse_applicant_data(applicant_data: str) -> dict[str, str]:
    parsed_data: dict[str, str] = {}

    for field_name, aliases in APPLICANT_FIELD_ALIASES.items():
        parsed_data[field_name] = ""
        for alias in sorted(aliases, key=len, reverse=True):
            pattern = rf"^\s*[-*]?\s*\**{re.escape(alias)}\**\s*:?\**\s*(.+?)\s*$"
            match = re.search(pattern, applicant_data, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                parsed_data[field_name] = match.group(1).strip()
                break

    return parsed_data

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Stealth Agent"
    app_version: str = "0.1.0"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: int = 15
    browser_headless: bool = True
    browser_timeout_ms: int = 15000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

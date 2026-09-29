import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


class Settings:
    DATABASE_URL = get_env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'code_review_agent.db'}")
    APP_ENV = get_env("APP_ENV", "development")
    AZURE_OPENAI_ENDPOINT = get_env("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_KEY = get_env("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_DEPLOYMENT = get_env("AZURE_OPENAI_DEPLOYMENT", "")
    AZURE_OPENAI_API_VERSION = get_env("AZURE_OPENAI_API_VERSION", "2024-02-01")


settings = Settings()


def ai_configured() -> bool:
    return bool(
        settings.AZURE_OPENAI_ENDPOINT
        and settings.AZURE_OPENAI_API_KEY
        and settings.AZURE_OPENAI_DEPLOYMENT
    )

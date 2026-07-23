"""
Centralizes all configuration loaded from environment variables.
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # -- Evolution API (WhatsApp) --
    EVOLUTION_API_URL: str = os.getenv("EVOLUTION_API_URL", "")
    EVOLUTION_API_KEY: str = os.getenv("EVOLUTION_API_KEY", "")
    EVOLUTION_INSTANCE: str = os.getenv("EVOLUTION_INSTANCE", "")
    WHATSAPP_GROUP_JID: str = os.getenv("WHATSAPP_GROUP_JID", "")

    # -- Google Sheets --
    GOOGLE_SHEETS_ID: str = os.getenv("GOOGLE_SHEETS_ID", "")
    GOOGLE_CREDENTIALS_PATH: str = os.getenv(
        "GOOGLE_CREDENTIALS_PATH", "secrets/google-service-account.json"
    )

    # -- OpenAI --
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # -- Logging --
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    @classmethod
    def validate(cls) -> None:
        """Raises ValueError if any required credential/setting is missing."""
        required = {
            "EVOLUTION_API_URL": cls.EVOLUTION_API_URL,
            "EVOLUTION_API_KEY": cls.EVOLUTION_API_KEY,
            "EVOLUTION_INSTANCE": cls.EVOLUTION_INSTANCE,
            "WHATSAPP_GROUP_JID": cls.WHATSAPP_GROUP_JID,
            "GOOGLE_SHEETS_ID": cls.GOOGLE_SHEETS_ID,
            "OPENAI_API_KEY": cls.OPENAI_API_KEY,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

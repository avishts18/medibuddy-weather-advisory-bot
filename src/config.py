"""
Configuration & LLM Factory for Weather-Advisory Support Bot
"""
import os
import logging
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger("weather_bot.config")

# Project Root Directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOP_PATH = os.getenv("SOP_FILE_PATH", str(PROJECT_ROOT / "data" / "sops.yaml"))

# Weather API Settings
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TIMEOUT = int(os.getenv("OPEN_METEO_TIMEOUT_SECONDS", "10"))

# Provider keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

LLM_PROVIDER_SETTING = os.getenv("LLM_PROVIDER", "auto").lower().strip()


def get_active_provider() -> str:
    """Determine the active LLM provider based on settings and available keys."""
    if LLM_PROVIDER_SETTING != "auto":
        return LLM_PROVIDER_SETTING

    if OPENAI_API_KEY:
        return "openai"
    elif GOOGLE_API_KEY:
        return "gemini"
    elif ANTHROPIC_API_KEY:
        return "anthropic"
    elif GROQ_API_KEY:
        return "groq"
    return "mock"


def get_llm(temperature: float = 0.0, provider_override: Optional[str] = None):
    """
    Returns an initialized ChatModel instance based on the active provider.
    Supports OpenAI, Google Gemini, Anthropic, Groq, and a Mock LLM for offline tests.
    """
    provider = provider_override or get_active_provider()

    try:
        if provider == "openai" and OPENAI_API_KEY:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=OPENAI_MODEL,
                temperature=temperature,
                api_key=OPENAI_API_KEY
            )

        elif provider == "gemini" and GOOGLE_API_KEY:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=GEMINI_MODEL,
                temperature=temperature,
                google_api_key=GOOGLE_API_KEY
            )

        elif provider == "anthropic" and ANTHROPIC_API_KEY:
            from langchain_community.chat_models import ChatAnthropic
            return ChatAnthropic(
                model=ANTHROPIC_MODEL,
                temperature=temperature,
                anthropic_api_key=ANTHROPIC_API_KEY
            )

        elif provider == "groq" and GROQ_API_KEY:
            from langchain_community.chat_models import ChatGroq
            return ChatGroq(
                model_name=GROQ_MODEL,
                temperature=temperature,
                groq_api_key=GROQ_API_KEY
            )
    except Exception as e:
        logger.warning(f"Failed to initialize provider '{provider}': {e}. Falling back to deterministic fallback engine.")

    # Fallback / Mock LLM
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    logger.info("Using Fallback / Offline Mock Chat Model.")
    return None

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

# Project Paths & Defaults
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOP_PATH = os.getenv("SOP_FILE_PATH", str(PROJECT_ROOT / "data" / "sops.yaml"))

# Open-Meteo Weather API Settings (100% Free, No Key Needed)
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TIMEOUT = int(os.getenv("OPEN_METEO_TIMEOUT_SECONDS", "10"))

# LLM Keys
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()


def get_active_provider() -> str:
    """Detects active LLM provider based on supplied key, or defaults to offline mode."""
    if GOOGLE_API_KEY:
        return "gemini"
    elif GROQ_API_KEY:
        return "groq"
    elif OPENAI_API_KEY:
        return "openai"
    elif ANTHROPIC_API_KEY:
        return "anthropic"
    return "offline_grounded"


def get_llm(temperature: float = 0.0, provider_override: Optional[str] = None):
    """
    Returns an initialized ChatModel instance based on available keys.
    If no key is configured, returns None to use the deterministic grounded engine.
    """
    provider = provider_override or get_active_provider()

    try:
        if provider == "gemini" and GOOGLE_API_KEY:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                temperature=temperature,
                google_api_key=GOOGLE_API_KEY
            )

        elif provider == "groq" and GROQ_API_KEY:
            from langchain_community.chat_models import ChatGroq
            return ChatGroq(
                model_name=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                temperature=temperature,
                groq_api_key=GROQ_API_KEY
            )

        elif provider == "openai" and OPENAI_API_KEY:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=temperature,
                api_key=OPENAI_API_KEY
            )

        elif provider == "anthropic" and ANTHROPIC_API_KEY:
            from langchain_community.chat_models import ChatAnthropic
            return ChatAnthropic(
                model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
                temperature=temperature,
                anthropic_api_key=ANTHROPIC_API_KEY
            )
    except Exception as e:
        logger.warning(f"Could not initialize LLM provider '{provider}': {e}. Using deterministic synthesis.")

    return None

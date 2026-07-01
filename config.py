"""Application configuration.

All secrets are read from environment variables (see .env.example).
No credentials are hard-coded in this file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from a local .env file (if present)
load_dotenv()

# --- Telegram API credentials (https://my.telegram.org) ---
API_ID: int = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")

# Telegram API request timeout (seconds)
TELEGRAM_API_TIMEOUT: float = float(os.getenv("TELEGRAM_API_TIMEOUT", "30.0"))

# --- Rate limiting / collection tuning ---
REQUEST_DELAY: float = float(os.getenv("REQUEST_DELAY", "1.0"))  # seconds between requests
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
PARTICIPANTS_BATCH_SIZE: int = int(os.getenv("PARTICIPANTS_BATCH_SIZE", "200"))

# --- Export / logging ---
DEFAULT_OUTPUT_DIR: Path = Path(os.getenv("OUTPUT_DIR", "./output"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = os.getenv("LOG_FILE", "analyzer.log")

# --- Database ---
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/analyzer",
)

# --- LLM: Anthropic Claude (direct API) ---
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-3-haiku-20240307")
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "4096"))

# --- LLM: OpenRouter (optional gateway) ---
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


def validate_config() -> bool:
    """Ensure the mandatory Telegram credentials are present."""
    if not API_ID or API_ID == 0:
        raise ValueError("TELEGRAM_API_ID is not set. Add it to your .env file.")
    if not API_HASH:
        raise ValueError("TELEGRAM_API_HASH is not set. Add it to your .env file.")
    return True

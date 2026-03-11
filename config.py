"""Configuration loaded from environment variables / .env file."""
import os

from dotenv import load_dotenv

# Prefer project-local .env values over previously exported shell variables.
load_dotenv(override=True)

# Required – validated at startup in bot.py
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Optional tunables
POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "10"))           # seconds
DB_PATH: str = os.getenv("DB_PATH", "bot.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

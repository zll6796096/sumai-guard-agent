from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mock_mode: bool = _env_bool("MOCK_MODE", True)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    analysis_timeout: int = int(os.getenv("ANALYSIS_TIMEOUT", "120"))
    version: str = "0.2.0"


settings = Settings()

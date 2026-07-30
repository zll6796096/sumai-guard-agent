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
    require_real_gemini: bool = _env_bool("REQUIRE_REAL_GEMINI", False)
    result_memo_ttl_seconds: int = int(os.getenv("RESULT_MEMO_TTL_SECONDS", "300"))
    result_memo_max_items: int = int(os.getenv("RESULT_MEMO_MAX_ITEMS", "128"))

    def __post_init__(self) -> None:
        if self.result_memo_ttl_seconds <= 0:
            raise ValueError("result_memo_ttl_seconds must be greater than zero")
        if self.result_memo_max_items <= 0:
            raise ValueError("result_memo_max_items must be greater than zero")


settings = Settings()

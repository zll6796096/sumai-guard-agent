"""Hermetic loader for the standalone SumaiGuard web application module."""

from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType


WEB_APP_PATH = Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"
WEB_IMPORT_ENVIRONMENT_KEYS = (
    "MOCK_MODE",
    "REQUIRE_REAL_GEMINI",
    "PUBLIC_WEB_ANALYSIS_ENABLED",
    "SUMAI_AGENT_TIMEOUT_SECONDS",
    "SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS",
    "SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS",
    "ANALYSIS_TIMEOUT",
    "SUMAI_AGENT_URL",
    "SUMAI_WEB_PORT",
    "LOG_LEVEL",
    "PYTHON_DOTENV_DISABLED",
)
LOCAL_WEB_ENVIRONMENT = {
    "MOCK_MODE": "true",
    "REQUIRE_REAL_GEMINI": "false",
    "SUMAI_AGENT_TIMEOUT_SECONDS": "150",
    "SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS": "120",
    "SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS": "30",
    "ANALYSIS_TIMEOUT": "120",
    "SUMAI_AGENT_URL": "http://localhost:8080",
    "SUMAI_WEB_PORT": "8081",
    "LOG_LEVEL": "INFO",
    "PYTHON_DOTENV_DISABLED": "1",
}


def load_web_module(
    environment: Mapping[str, str] | None = None,
) -> ModuleType:
    previous_environment = {
        name: os.environ.get(name) for name in WEB_IMPORT_ENVIRONMENT_KEYS
    }
    module_name = f"sumai_web_test_{uuid.uuid4().hex}"
    module: ModuleType | None = None
    try:
        for name in WEB_IMPORT_ENVIRONMENT_KEYS:
            os.environ.pop(name, None)
        os.environ.update(LOCAL_WEB_ENVIRONMENT)
        if environment:
            os.environ.update(environment)

        sys.modules.pop("public_pages", None)
        spec = importlib.util.spec_from_file_location(module_name, WEB_APP_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop("public_pages", None)
        for name, previous_value in previous_environment.items():
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous_value


__all__ = [
    "LOCAL_WEB_ENVIRONMENT",
    "WEB_APP_PATH",
    "WEB_IMPORT_ENVIRONMENT_KEYS",
    "load_web_module",
]

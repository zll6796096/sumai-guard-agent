from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
TEST_FILE = Path(__file__).resolve()
CONFIG_ENV_NAMES = (
    "APP_CHECK_REQUIRED",
    "FIREBASE_APP_ID",
    "MAX_UPLOAD_BYTES",
    "MAX_SOURCE_PIXELS",
)


def _run_isolated_config(
    *,
    config_env: dict[str, str] | None = None,
    settings_kwargs: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in CONFIG_ENV_NAMES:
        env.pop(name, None)
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env["PYTHONPATH"] = str(APP_ROOT)
    env.update(config_env or {})
    env["SUMAI_TEST_SETTINGS_KWARGS"] = json.dumps(settings_kwargs or {})
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, os; "
                "kwargs = json.loads(os.environ.pop('SUMAI_TEST_SETTINGS_KWARGS')); "
                "from app.config import Settings; "
                "value = Settings(**kwargs); "
                "print(json.dumps({"
                "'app_check_required': value.app_check_required, "
                "'firebase_app_id': value.firebase_app_id, "
                "'max_upload_bytes': value.max_upload_bytes, "
                "'max_source_pixels': value.max_source_pixels, "
                "'version': value.version"
                "}))"
            ),
        ],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )


def test_module_collects_under_hostile_outer_app_check_config() -> None:
    env = os.environ.copy()
    env["APP_CHECK_REQUIRED"] = "definitely-not-true"
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env["PYTHONPATH"] = str(APP_ROOT)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(TEST_FILE)],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.fixture
def local_defaults_with_configured_outer_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")
    monkeypatch.setenv("FIREBASE_APP_ID", "outer-firebase-app")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "99")
    monkeypatch.setenv("MAX_SOURCE_PIXELS", "101")

    result = _run_isolated_config()

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_app_check_is_optional_for_local_defaults(
    local_defaults_with_configured_outer_environment: dict[str, object],
) -> None:
    assert (
        local_defaults_with_configured_outer_environment["app_check_required"] is False
    )


def test_upload_limit_defaults_to_ten_mebibytes(
    local_defaults_with_configured_outer_environment: dict[str, object],
) -> None:
    assert local_defaults_with_configured_outer_environment["max_upload_bytes"] == (
        10 * 1024 * 1024
    )


def test_source_pixel_limit_defaults_to_twenty_five_million(
    local_defaults_with_configured_outer_environment: dict[str, object],
) -> None:
    assert (
        local_defaults_with_configured_outer_environment["max_source_pixels"]
        == 25_000_000
    )


def test_version_defaults_to_zero_point_three(
    local_defaults_with_configured_outer_environment: dict[str, object],
) -> None:
    assert local_defaults_with_configured_outer_environment["version"] == "0.3.0"


@pytest.mark.parametrize("raw_value", ["tru", "definitely-not-true"])
def test_malformed_app_check_flag_fails_closed_without_echoing_value(raw_value: str) -> None:
    result = _run_isolated_config(config_env={"APP_CHECK_REQUIRED": raw_value})

    assert result.returncode != 0
    assert "APP_CHECK_REQUIRED" in result.stderr
    assert raw_value not in result.stderr


@pytest.mark.parametrize("raw_value", ["", "   \t"], ids=["empty", "whitespace"])
def test_present_but_blank_app_check_flag_fails_closed(raw_value: str) -> None:
    result = _run_isolated_config(config_env={"APP_CHECK_REQUIRED": raw_value})

    assert result.returncode != 0
    assert result.stderr.rstrip().endswith("ValueError: APP_CHECK_REQUIRED")


@pytest.mark.parametrize("raw_value", ["1", " true ", "YES", "On"])
def test_app_check_accepts_strict_true_tokens(raw_value: str) -> None:
    result = _run_isolated_config(
        config_env={
            "APP_CHECK_REQUIRED": raw_value,
            "FIREBASE_APP_ID": "firebase-test-app",
        }
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["app_check_required"] is True


@pytest.mark.parametrize("raw_value", ["0", " false ", "NO", "Off"])
def test_app_check_accepts_strict_false_tokens(raw_value: str) -> None:
    result = _run_isolated_config(config_env={"APP_CHECK_REQUIRED": raw_value})

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["app_check_required"] is False


def test_required_app_check_rejects_blank_firebase_app_id() -> None:
    result = _run_isolated_config(
        settings_kwargs={"app_check_required": True, "firebase_app_id": ""}
    )

    assert result.returncode != 0
    assert result.stderr.rstrip().endswith("ValueError: firebase_app_id")


def test_required_app_check_rejects_whitespace_firebase_app_id() -> None:
    result = _run_isolated_config(
        settings_kwargs={"app_check_required": True, "firebase_app_id": "   \t"}
    )

    assert result.returncode != 0
    assert result.stderr.rstrip().endswith("ValueError: firebase_app_id")


def test_disabled_app_check_accepts_blank_firebase_app_id() -> None:
    result = _run_isolated_config(
        settings_kwargs={"app_check_required": False, "firebase_app_id": ""}
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["firebase_app_id"] == ""


@pytest.mark.parametrize("field_name", ["max_upload_bytes", "max_source_pixels"])
@pytest.mark.parametrize("invalid_value", [0, -1])
def test_image_limits_must_be_positive(field_name: str, invalid_value: int) -> None:
    result = _run_isolated_config(settings_kwargs={field_name: invalid_value})

    assert result.returncode != 0
    assert result.stderr.rstrip().endswith(f"ValueError: {field_name}")


@pytest.mark.parametrize("field_name", ["max_upload_bytes", "max_source_pixels"])
def test_image_limits_accept_one(field_name: str) -> None:
    result = _run_isolated_config(settings_kwargs={field_name: 1})

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[field_name] == 1

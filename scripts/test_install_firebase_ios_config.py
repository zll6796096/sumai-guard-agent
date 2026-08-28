from __future__ import annotations

import base64
import importlib.util
import plistlib
import stat
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_firebase_ios_config.py"
SPEC = importlib.util.spec_from_file_location("install_firebase_ios_config", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

APP_ID = "1:123456789:ios:abcdef0123456789"


def valid_config() -> bytes:
    return plistlib.dumps(
        {
            "API_KEY": "test-client-value",
            "BUNDLE_ID": "com.zll.sumaiguard",
            "GCM_SENDER_ID": "123456789",
            "GOOGLE_APP_ID": APP_ID,
            "PROJECT_ID": "sumai-test-project",
        }
    )


def test_selects_one_exact_active_ios_app() -> None:
    payload = {
        "apps": [
            {
                "appId": APP_ID,
                "bundleId": "com.zll.sumaiguard",
                "name": f"projects/sumai-test-project/iosApps/{APP_ID}",
                "state": "ACTIVE",
            }
        ]
    }

    assert MODULE.select_app_name(
        payload,
        bundle_id="com.zll.sumaiguard",
        expected_app_id=APP_ID,
    ) == f"projects/sumai-test-project/iosApps/{APP_ID}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("BUNDLE_ID", "com.example.other"),
        ("GOOGLE_APP_ID", "1:123456789:ios:ffffffffffffffff"),
        ("GCM_SENDER_ID", "999999999"),
        ("PROJECT_ID", "other-project"),
    ],
)
def test_rejects_mismatched_downloaded_configuration(
    field: str,
    value: str,
) -> None:
    config = plistlib.loads(valid_config())
    config[field] = value

    with pytest.raises(MODULE.ConfigError):
        MODULE.validate_config(
            plistlib.dumps(config),
            bundle_id="com.zll.sumaiguard",
            expected_app_id=APP_ID,
            project_id="sumai-test-project",
        )


def test_writes_validated_config_atomically_with_private_mode(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "Resources" / "GoogleService-Info.plist"

    MODULE.write_config(destination, valid_config())

    assert destination.read_bytes() == valid_config()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_installs_valid_config_from_named_environment_variable(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "Resources" / "GoogleService-Info.plist"
    variable = "FIREBASE_IOS_CONFIG_BASE64"

    MODULE.install_from_environment(
        environment={variable: base64.b64encode(valid_config()).decode("ascii")},
        variable=variable,
        project_id="sumai-test-project",
        expected_app_id=APP_ID,
        bundle_id="com.zll.sumaiguard",
        destination=destination,
    )

    assert destination.read_bytes() == valid_config()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"FIREBASE_IOS_CONFIG_BASE64": "not-base64"},
    ],
)
def test_environment_install_fails_closed_without_writing(
    tmp_path: Path,
    environment: dict[str, str],
) -> None:
    destination = tmp_path / "Resources" / "GoogleService-Info.plist"

    with pytest.raises(MODULE.ConfigError):
        MODULE.install_from_environment(
            environment=environment,
            variable="FIREBASE_IOS_CONFIG_BASE64",
            project_id="sumai-test-project",
            expected_app_id=APP_ID,
            bundle_id="com.zll.sumaiguard",
            destination=destination,
        )

    assert not destination.exists()

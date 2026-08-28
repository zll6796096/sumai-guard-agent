from __future__ import annotations

import base64
import os
import plistlib
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POST_CLONE = ROOT / "ios" / "ci_scripts" / "ci_post_clone.sh"
INSTALLER = ROOT / "scripts" / "install_firebase_ios_config.py"
APP_ID = "1:788259830737:ios:1715e5481afc3b9097bef0"


def cloud_config() -> bytes:
    return plistlib.dumps(
        {
            "API_KEY": "test-client-value",
            "BUNDLE_ID": "com.zll.sumaiguard",
            "GCM_SENDER_ID": "788259830737",
            "GOOGLE_APP_ID": APP_ID,
            "PROJECT_ID": "zhang23-23",
        }
    )


def test_post_clone_script_uses_redacted_firebase_environment_flow() -> None:
    content = POST_CLONE.read_text(encoding="utf-8")

    assert content.startswith("#!/bin/sh\n")
    assert "set -eu" in content
    assert "CI_PRIMARY_REPOSITORY_PATH" in content
    assert "--config-base64-env FIREBASE_IOS_CONFIG_BASE64" in content
    assert "ios/SumaiGuard/Resources/GoogleService-Info.plist" in content
    assert "set -x" not in content
    assert "echo $FIREBASE_IOS_CONFIG_BASE64" not in content
    assert "echo \"$FIREBASE_IOS_CONFIG_BASE64\"" not in content
    assert stat.S_IMODE(POST_CLONE.stat().st_mode) & stat.S_IXUSR


def test_post_clone_script_has_valid_shell_syntax() -> None:
    result = subprocess.run(
        ["/bin/sh", "-n", str(POST_CLONE)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_post_clone_script_installs_config_without_logging_value(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(INSTALLER, scripts / INSTALLER.name)
    encoded = base64.b64encode(cloud_config()).decode("ascii")
    environment = os.environ.copy()
    environment.update(
        {
            "CI_PRIMARY_REPOSITORY_PATH": str(tmp_path),
            "FIREBASE_IOS_CONFIG_BASE64": encoded,
        }
    )

    result = subprocess.run(
        [str(POST_CLONE)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    destination = (
        tmp_path
        / "ios"
        / "SumaiGuard"
        / "Resources"
        / "GoogleService-Info.plist"
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert destination.read_bytes() == cloud_config()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert encoded not in combined
    assert "test-client-value" not in combined
    assert "firebase_ios_config=PASS" in result.stdout

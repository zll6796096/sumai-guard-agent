from __future__ import annotations

import importlib.util
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_effective_release_build_settings_require_entitlement_binding() -> None:
    module = load_script("validate_ios_build_settings")
    complete = """\
    CONFIGURATION = Release
    CODE_SIGN_ENTITLEMENTS = SumaiGuard/SumaiGuard.entitlements
    ENABLE_TESTABILITY = NO
    PRODUCT_BUNDLE_IDENTIFIER = com.zll.sumaiguard
    SWIFT_ACTIVE_COMPILATION_CONDITIONS =
"""

    assert module.validate(complete) == []
    assert "ENTITLEMENTS_UNBOUND" in module.validate(
        complete.replace(
            "SumaiGuard/SumaiGuard.entitlements",
            "",
        )
    )


def test_effective_release_build_settings_reject_debug_or_testability() -> None:
    module = load_script("validate_ios_build_settings")
    unsafe = """\
    CONFIGURATION = Release
    CODE_SIGN_ENTITLEMENTS = SumaiGuard/SumaiGuard.entitlements
    ENABLE_TESTABILITY = YES
    PRODUCT_BUNDLE_IDENTIFIER = com.zll.sumaiguard
    SWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG
"""

    findings = module.validate(unsafe)

    assert "RELEASE_TESTABILITY_ENABLED" in findings
    assert "RELEASE_DEBUG_CONDITION" in findings


def make_signed_app_fixture(root: Path) -> Path:
    app = root / "SumaiGuard.app"
    app.mkdir(parents=True)
    with (app / "Info.plist").open("wb") as stream:
        plistlib.dump(
            {"CFBundleIdentifier": "com.zll.sumaiguard"},
            stream,
        )
    with (app / "GoogleService-Info.plist").open("wb") as stream:
        plistlib.dump(
            {
                "BUNDLE_ID": "com.zll.sumaiguard",
                "GOOGLE_APP_ID": "1:123456789:ios:abcdef0123456789",
            },
            stream,
        )
    return app


def test_signed_app_requires_production_app_attest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_script("validate_ios_signed_app")
    app = make_signed_app_fixture(tmp_path)

    def fake_codesign(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=plistlib.dumps(
                {
                    "application-identifier": "TEAM.com.zll.sumaiguard",
                    "com.apple.developer.team-identifier": "TEAM",
                    "com.apple.developer.devicecheck.appattest-environment": (
                        "production"
                    ),
                }
            ),
            stderr=b"",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_codesign)
    assert module.validate(
        app,
        "1:123456789:ios:abcdef0123456789",
    ) == []

    def fake_development_codesign(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=plistlib.dumps(
                {
                    "application-identifier": "TEAM.com.zll.sumaiguard",
                    "com.apple.developer.team-identifier": "TEAM",
                    "com.apple.developer.devicecheck.appattest-environment": (
                        "development"
                    ),
                }
            ),
            stderr=b"",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_development_codesign)
    assert "APP_ATTEST_NOT_PRODUCTION" in module.validate(
        app,
        "1:123456789:ios:abcdef0123456789",
    )


def test_signed_app_rejects_firebase_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_script("validate_ios_signed_app")
    app = make_signed_app_fixture(tmp_path)

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=plistlib.dumps(
                {
                    "application-identifier": "TEAM.com.zll.sumaiguard",
                    "com.apple.developer.team-identifier": "TEAM",
                    "com.apple.developer.devicecheck.appattest-environment": (
                        "production"
                    ),
                }
            ),
            stderr=b"",
        ),
    )

    assert "FIREBASE_IDENTITY_MISMATCH" in module.validate(
        app,
        "1:123456789:ios:ffffffffffffffff",
    )

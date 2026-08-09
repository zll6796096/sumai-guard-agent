from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate_ios_release.py"


class ReleaseFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.project = root / "ios" / "project.yml"
        self.info = root / "ios" / "SumaiGuard" / "Info.plist"
        self.entitlements = root / "ios" / "SumaiGuard" / "SumaiGuard.entitlements"
        self.release_config = root / "ios" / "SumaiGuard" / "Config" / "Release.xcconfig"
        self.source = root / "ios" / "SumaiGuard" / "Services" / "AppCheckBootstrap.swift"
        self.pbx = root / "ios" / "SumaiGuard.xcodeproj" / "project.pbxproj"
        self.package_resolved = (
            root
            / "ios"
            / "SumaiGuard.xcodeproj"
            / "project.xcworkspace"
            / "xcshareddata"
            / "swiftpm"
            / "Package.resolved"
        )
        self.app_icon = (
            root
            / "ios"
            / "SumaiGuard"
            / "Resources"
            / "Assets.xcassets"
            / "AppIcon.appiconset"
            / "AppIcon-1024.png"
        )
        self.icon_contents = self.app_icon.parent / "Contents.json"

    def write_text(self, path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def write_plist(self, path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            plistlib.dump(value, stream)

    def make_icon(
        self,
        *,
        size: tuple[int, int] = (1024, 1024),
        mode: str = "RGB",
        alpha: int = 255,
    ) -> None:
        self.app_icon.parent.mkdir(parents=True, exist_ok=True)
        if mode == "RGBA":
            color: tuple[int, ...] = (23, 61, 50, alpha)
        else:
            color = (23, 61, 50)
        Image.new(mode, size, color).save(self.app_icon, format="PNG")


@pytest.fixture
def release_fixture(tmp_path: Path) -> ReleaseFixture:
    fixture = ReleaseFixture(tmp_path)
    fixture.write_text(
        fixture.project,
        """\
name: SumaiGuard
options:
  deploymentTarget:
    iOS: "17.0"
packages:
  Firebase:
    url: https://github.com/firebase/firebase-ios-sdk.git
    exactVersion: 12.17.0
targets:
  SumaiGuard:
    type: application
    platform: iOS
    deploymentTarget: "17.0"
    settings:
      base:
        ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon
        CURRENT_PROJECT_VERSION: 1
        MARKETING_VERSION: "1.0"
        PRODUCT_BUNDLE_IDENTIFIER: com.zll.sumaiguard
        TARGETED_DEVICE_FAMILY: "1"
""",
    )
    fixture.write_plist(
        fixture.info,
        {
            "CFBundleDisplayName": "実家チェック",
            "CFBundleName": "実家あんしんチェック",
            "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
            "CFBundleShortVersionString": "$(MARKETING_VERSION)",
            "CFBundleVersion": "$(CURRENT_PROJECT_VERSION)",
            "LSRequiresIPhoneOS": True,
            "SUMAI_API_ORIGIN": "$(SUMAI_API_ORIGIN)",
        },
    )
    fixture.write_plist(
        fixture.entitlements,
        {"com.apple.developer.devicecheck.appattest-environment": "production"},
    )
    fixture.write_text(
        fixture.release_config,
        "SUMAI_API_ORIGIN = https:/$()/api.sumaiguard.example\n"
        "CODE_SIGN_ENTITLEMENTS = SumaiGuard/SumaiGuard.entitlements\n",
    )
    fixture.write_text(
        fixture.source,
        """\
#if DEBUG
let provider = AppCheckDebugProviderFactory()
#else
let provider = AppAttestProviderFactory()
#endif
""",
    )
    fixture.write_text(
        fixture.pbx,
        """\
/* SumaiGuard */ = { productName = SumaiGuard; };
/* Debug */ = {
  buildSettings = {
    ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
    CURRENT_PROJECT_VERSION = 1;
    IPHONEOS_DEPLOYMENT_TARGET = 17.0;
    MARKETING_VERSION = 1.0;
    PRODUCT_BUNDLE_IDENTIFIER = com.zll.sumaiguard;
    TARGETED_DEVICE_FAMILY = 1;
  };
  name = Debug;
};
/* Release */ = {
  buildSettings = {
    ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
    CURRENT_PROJECT_VERSION = 1;
    IPHONEOS_DEPLOYMENT_TARGET = 17.0;
    MARKETING_VERSION = 1.0;
    PRODUCT_BUNDLE_IDENTIFIER = com.zll.sumaiguard;
    TARGETED_DEVICE_FAMILY = 1;
  };
  name = Release;
};
repositoryURL = "https://github.com/firebase/firebase-ios-sdk.git";
requirement = {
  kind = exactVersion;
  version = 12.17.0;
};
""",
    )
    fixture.write_text(
        fixture.package_resolved,
        json.dumps(
            {
                "pins": [
                    {
                        "identity": "firebase-ios-sdk",
                        "kind": "remoteSourceControl",
                        "location": "https://github.com/firebase/firebase-ios-sdk.git",
                        "state": {"revision": "a" * 40, "version": "12.17.0"},
                    }
                ],
                "version": 3,
            }
        ),
    )
    fixture.write_text(
        fixture.icon_contents,
        json.dumps(
            {
                "images": [
                    {
                        "filename": fixture.app_icon.name,
                        "idiom": "ios-marketing",
                        "scale": "1x",
                        "size": "1024x1024",
                    }
                ],
                "info": {"author": "xcode", "version": 1},
            }
        ),
    )
    fixture.make_icon()
    return fixture


def run_validator(
    fixture: ReleaseFixture,
    *,
    allow_invalid_origin: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(VALIDATOR), "--root", str(fixture.root)]
    if allow_invalid_origin:
        command.append("--allow-invalid-api-origin-for-ci")
    return subprocess.run(command, capture_output=True, text=True, check=False)


def assert_failed_with(result: subprocess.CompletedProcess[str], code: str) -> None:
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"ERROR {code} " in result.stdout


def test_accepts_complete_production_release(release_fixture: ReleaseFixture) -> None:
    result = run_validator(release_fixture)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "PASS IOS_RELEASE_VALIDATION\n"
    assert result.stderr == ""


def test_rejects_absent_app_store_icon(release_fixture: ReleaseFixture) -> None:
    release_fixture.app_icon.unlink()

    assert_failed_with(run_validator(release_fixture), "ICON_FILE_MISSING")


def test_rejects_transparent_app_store_icon(release_fixture: ReleaseFixture) -> None:
    release_fixture.make_icon(mode="RGBA", alpha=0)

    result = run_validator(release_fixture)

    assert_failed_with(result, "ICON_TRANSPARENT")
    assert "ERROR ICON_ALPHA_CHANNEL " in result.stdout


def test_rejects_fully_opaque_alpha_channel(release_fixture: ReleaseFixture) -> None:
    release_fixture.make_icon(mode="RGBA", alpha=255)

    assert_failed_with(run_validator(release_fixture), "ICON_ALPHA_CHANNEL")


def test_rejects_wrong_app_store_icon_dimensions(release_fixture: ReleaseFixture) -> None:
    release_fixture.make_icon(size=(1023, 1024))

    assert_failed_with(run_validator(release_fixture), "ICON_SIZE_INVALID")


@pytest.mark.parametrize("value", [None, "development", "sandbox", ""])
def test_rejects_missing_or_wrong_production_app_attest_entitlement(
    release_fixture: ReleaseFixture,
    value: str | None,
) -> None:
    payload = {} if value is None else {
        "com.apple.developer.devicecheck.appattest-environment": value
    }
    release_fixture.write_plist(release_fixture.entitlements, payload)

    assert_failed_with(run_validator(release_fixture), "APP_ATTEST_NOT_PRODUCTION")


def test_rejects_debug_provider_compiled_into_release(release_fixture: ReleaseFixture) -> None:
    release_fixture.write_text(
        release_fixture.source,
        "let provider = AppCheckDebugProviderFactory()\n",
    )

    assert_failed_with(run_validator(release_fixture), "RELEASE_DEBUG_PROVIDER")


def test_allows_debug_provider_only_inside_debug_branch(release_fixture: ReleaseFixture) -> None:
    result = run_validator(release_fixture)

    assert result.returncode == 0, result.stdout + result.stderr


def test_rejects_debug_token_marker_in_release_settings(release_fixture: ReleaseFixture) -> None:
    release_fixture.write_text(
        release_fixture.release_config,
        "SUMAI_API_ORIGIN = https:/$()/api.sumaiguard.example\n"
        "FIRAppCheckDebugToken = top-secret-token\n",
    )

    assert_failed_with(run_validator(release_fixture), "RELEASE_DEBUG_TOKEN")


@pytest.mark.parametrize(
    ("origin", "code"),
    [
        ("https:/$()/localhost", "API_ORIGIN_LOOPBACK"),
        ("https:/$()/127.0.0.1", "API_ORIGIN_LOOPBACK"),
        ("https:/$()/api.invalid", "API_ORIGIN_PLACEHOLDER"),
        ("http:/$()/api.sumaiguard.example", "API_ORIGIN_CLEARTEXT"),
    ],
)
def test_rejects_unsafe_release_origin(
    release_fixture: ReleaseFixture,
    origin: str,
    code: str,
) -> None:
    release_fixture.write_text(
        release_fixture.release_config,
        f"SUMAI_API_ORIGIN = {origin}\n",
    )

    assert_failed_with(run_validator(release_fixture), code)


def test_rejects_hardcoded_unsafe_url_in_release_source(release_fixture: ReleaseFixture) -> None:
    release_fixture.write_text(
        release_fixture.source,
        'let releaseOrigin = "http://127.0.0.1:8080"\n',
    )

    result = run_validator(release_fixture)

    assert_failed_with(result, "RELEASE_CLEARTEXT_URL")
    assert "ERROR RELEASE_LOOPBACK_URL " in result.stdout


def test_ci_flag_allows_only_exact_invalid_origin_placeholder(
    release_fixture: ReleaseFixture,
) -> None:
    release_fixture.write_text(
        release_fixture.release_config,
        "SUMAI_API_ORIGIN = https:/$()/invalid.invalid\n",
    )

    ordinary = run_validator(release_fixture)
    ci = run_validator(release_fixture, allow_invalid_origin=True)

    assert_failed_with(ordinary, "API_ORIGIN_PLACEHOLDER")
    assert ci.returncode == 0, ci.stdout + ci.stderr


@pytest.mark.parametrize(
    "break_gate",
    ["icon", "entitlement", "debug-provider", "identity", "deployment", "firebase-pin"],
)
def test_ci_flag_never_bypasses_non_origin_gates(
    release_fixture: ReleaseFixture,
    break_gate: str,
) -> None:
    release_fixture.write_text(
        release_fixture.release_config,
        "SUMAI_API_ORIGIN = https:/$()/invalid.invalid\n",
    )
    if break_gate == "icon":
        release_fixture.app_icon.unlink()
    elif break_gate == "entitlement":
        release_fixture.write_plist(release_fixture.entitlements, {})
    elif break_gate == "debug-provider":
        release_fixture.write_text(
            release_fixture.source,
            "let provider = AppCheckDebugProviderFactory()\n",
        )
    elif break_gate == "identity":
        release_fixture.write_plist(
            release_fixture.info,
            {
                "CFBundleDisplayName": "別名",
                "CFBundleName": "実家あんしんチェック",
                "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
                "CFBundleShortVersionString": "$(MARKETING_VERSION)",
                "CFBundleVersion": "$(CURRENT_PROJECT_VERSION)",
            },
        )
    elif break_gate == "deployment":
        release_fixture.write_text(
            release_fixture.project,
            release_fixture.project.read_text(encoding="utf-8").replace('"17.0"', '"16.0"'),
        )
    else:
        release_fixture.write_text(
            release_fixture.project,
            release_fixture.project.read_text(encoding="utf-8").replace(
                "exactVersion: 12.17.0", "from: 12.17.0"
            ),
        )

    result = run_validator(release_fixture, allow_invalid_origin=True)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "API_ORIGIN_PLACEHOLDER" not in result.stdout


@pytest.mark.parametrize(
    ("path_name", "old", "new", "code"),
    [
        ("project", "com.zll.sumaiguard", "com.example.other", "IDENTITY_BUNDLE_MISMATCH"),
        ("info", "実家チェック", "別名", "IDENTITY_DISPLAY_NAME_MISMATCH"),
        ("info", "実家あんしんチェック", "別名", "IDENTITY_NAME_MISMATCH"),
        ("pbx", "MARKETING_VERSION = 1.0", "MARKETING_VERSION = 2.0", "IDENTITY_VERSION_MISMATCH"),
        ("pbx", "CURRENT_PROJECT_VERSION = 1", "CURRENT_PROJECT_VERSION = 2", "IDENTITY_BUILD_MISMATCH"),
    ],
)
def test_rejects_identity_mismatch_across_project_plist_and_pbx(
    release_fixture: ReleaseFixture,
    path_name: str,
    old: str,
    new: str,
    code: str,
) -> None:
    path = getattr(release_fixture, path_name)
    if path.suffix == ".plist":
        with path.open("rb") as stream:
            payload = plistlib.load(stream)
        payload = {key: new if value == old else value for key, value in payload.items()}
        release_fixture.write_plist(path, payload)
    else:
        release_fixture.write_text(
            path,
            path.read_text(encoding="utf-8").replace(old, new),
        )

    assert_failed_with(run_validator(release_fixture), code)


def test_rejects_ipad_target(release_fixture: ReleaseFixture) -> None:
    release_fixture.write_text(
        release_fixture.project,
        release_fixture.project.read_text(encoding="utf-8").replace(
            'TARGETED_DEVICE_FAMILY: "1"', 'TARGETED_DEVICE_FAMILY: "1,2"'
        ),
    )

    assert_failed_with(run_validator(release_fixture), "DEVICE_FAMILY_NOT_IPHONE_ONLY")


def test_rejects_deployment_target_below_ios_17(release_fixture: ReleaseFixture) -> None:
    release_fixture.write_text(
        release_fixture.project,
        release_fixture.project.read_text(encoding="utf-8").replace('"17.0"', '"16.4"'),
    )

    assert_failed_with(run_validator(release_fixture), "DEPLOYMENT_TARGET_TOO_LOW")


def test_rejects_unpinned_firebase_dependency(release_fixture: ReleaseFixture) -> None:
    release_fixture.write_text(
        release_fixture.project,
        release_fixture.project.read_text(encoding="utf-8").replace(
            "exactVersion: 12.17.0", "from: 12.17.0"
        ),
    )

    assert_failed_with(run_validator(release_fixture), "FIREBASE_NOT_EXACTLY_PINNED")


@pytest.mark.parametrize("malformed", ["project", "plist", "asset-json"])
def test_malformed_inputs_fail_closed_without_traceback(
    release_fixture: ReleaseFixture,
    malformed: str,
) -> None:
    if malformed == "project":
        release_fixture.write_text(release_fixture.project, "targets: [\n")
    elif malformed == "plist":
        release_fixture.write_text(release_fixture.entitlements, "not a plist\n")
    else:
        release_fixture.write_text(release_fixture.icon_contents, "{\n")

    result = run_validator(release_fixture)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ERROR INPUT_PARSE_FAILED " in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_errors_never_echo_secret_values_or_google_plist_contents(
    release_fixture: ReleaseFixture,
) -> None:
    secret = "AIzaSyNeverPrintThisValue"
    google_plist = (
        release_fixture.root
        / "ios"
        / "SumaiGuard"
        / "Resources"
        / "GoogleService-Info.plist"
    )
    release_fixture.write_plist(
        google_plist,
        {"API_KEY": secret, "BUNDLE_ID": "private-bundle-value"},
    )
    release_fixture.write_text(
        release_fixture.release_config,
        "SUMAI_API_ORIGIN = https:/$()/invalid.invalid\n"
        f"FIRAppCheckDebugToken = {secret}\n",
    )

    result = run_validator(release_fixture)
    combined = result.stdout + result.stderr

    assert result.returncode == 1
    assert secret not in combined
    assert "private-bundle-value" not in combined
    assert "GoogleService-Info.plist" not in combined
    assert "ERROR RELEASE_DEBUG_TOKEN ios/SumaiGuard/Config/Release.xcconfig " in result.stdout

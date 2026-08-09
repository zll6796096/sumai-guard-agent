#!/usr/bin/env python3
"""Validate the signed iOS app identity and effective App Attest entitlement."""

from __future__ import annotations

import argparse
import plistlib
import subprocess
from pathlib import Path
from typing import Any


MAX_PLIST_BYTES = 2 * 1024 * 1024
EXPECTED_BUNDLE = "com.zll.sumaiguard"


def read_plist(path: Path) -> dict[str, Any] | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > MAX_PLIST_BYTES:
        return None
    try:
        value = plistlib.loads(payload)
    except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError):
        return None
    return value if isinstance(value, dict) else None


def signed_entitlements(app: Path) -> dict[str, Any] | None:
    result = subprocess.run(
        ["/usr/bin/codesign", "-d", "--entitlements", ":-", str(app)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) > MAX_PLIST_BYTES:
        return None
    try:
        value = plistlib.loads(result.stdout)
    except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError):
        return None
    return value if isinstance(value, dict) else None


def validate(app: Path, expected_firebase_app_id: str) -> list[str]:
    findings: list[str] = []
    info = read_plist(app / "Info.plist")
    firebase = read_plist(app / "GoogleService-Info.plist")
    entitlements = signed_entitlements(app)

    if info is None or info.get("CFBundleIdentifier") != EXPECTED_BUNDLE:
        findings.append("BUNDLE_IDENTITY_MISMATCH")
    if firebase is None or (
        firebase.get("BUNDLE_ID") != EXPECTED_BUNDLE
        or firebase.get("GOOGLE_APP_ID") != expected_firebase_app_id
    ):
        findings.append("FIREBASE_IDENTITY_MISMATCH")
    if entitlements is None:
        findings.append("SIGNED_ENTITLEMENTS_INVALID")
    else:
        if (
            entitlements.get(
                "com.apple.developer.devicecheck.appattest-environment"
            )
            != "production"
        ):
            findings.append("APP_ATTEST_NOT_PRODUCTION")
        team = entitlements.get("com.apple.developer.team-identifier")
        application_id = entitlements.get("application-identifier")
        if (
            not isinstance(team, str)
            or not team
            or application_id != f"{team}.{EXPECTED_BUNDLE}"
        ):
            findings.append("SIGNED_IDENTITY_MISMATCH")
    return sorted(findings)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--app", type=Path)
    source.add_argument("--archive", type=Path)
    parser.add_argument("--expected-firebase-app-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app = args.app
    if args.archive is not None:
        app = args.archive / "Products" / "Applications" / "SumaiGuard.app"
    assert app is not None
    findings = validate(app.resolve(), args.expected_firebase_app_id)
    if findings:
        for finding in findings:
            print(f"ERROR IOS_SIGNED_APP {finding}")
        return 1
    print("PASS IOS_SIGNED_APP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

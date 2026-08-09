#!/usr/bin/env python3
"""Validate effective Xcode Release settings without echoing their values."""

from __future__ import annotations

import re
import sys


MAX_INPUT_BYTES = 4 * 1024 * 1024
EXPECTED = {
    "CONFIGURATION": "Release",
    "CODE_SIGN_ENTITLEMENTS": "SumaiGuard/SumaiGuard.entitlements",
    "PRODUCT_BUNDLE_IDENTIFIER": "com.zll.sumaiguard",
}


def parse_settings(payload: str) -> dict[str, str]:
    settings: dict[str, str] = {}
    for line in payload.splitlines():
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match:
            settings[match.group(1)] = match.group(2)
    return settings


def validate(payload: str) -> list[str]:
    settings = parse_settings(payload)
    findings: list[str] = []
    if settings.get("CONFIGURATION") != EXPECTED["CONFIGURATION"]:
        findings.append("NOT_RELEASE_CONFIGURATION")
    if settings.get("CODE_SIGN_ENTITLEMENTS") != EXPECTED["CODE_SIGN_ENTITLEMENTS"]:
        findings.append("ENTITLEMENTS_UNBOUND")
    if (
        settings.get("PRODUCT_BUNDLE_IDENTIFIER")
        != EXPECTED["PRODUCT_BUNDLE_IDENTIFIER"]
    ):
        findings.append("BUNDLE_IDENTITY_MISMATCH")
    if settings.get("ENABLE_TESTABILITY") == "YES":
        findings.append("RELEASE_TESTABILITY_ENABLED")
    conditions = settings.get("SWIFT_ACTIVE_COMPILATION_CONDITIONS", "").split()
    if "DEBUG" in conditions:
        findings.append("RELEASE_DEBUG_CONDITION")
    return sorted(findings)


def main() -> int:
    payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        print("ERROR IOS_RELEASE_BUILD_SETTINGS INPUT_TOO_LARGE")
        return 1
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        print("ERROR IOS_RELEASE_BUILD_SETTINGS INPUT_INVALID")
        return 1
    findings = validate(text)
    if findings:
        for finding in findings:
            print(f"ERROR IOS_RELEASE_BUILD_SETTINGS {finding}")
        return 1
    print("PASS IOS_RELEASE_BUILD_SETTINGS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

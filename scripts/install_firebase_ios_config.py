#!/usr/bin/env python3
"""Install validated Firebase iOS client configuration without logging values."""

from __future__ import annotations

import argparse
import base64
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = (
    ROOT / "ios" / "SumaiGuard" / "Resources" / "GoogleService-Info.plist"
)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
APP_ID_PATTERN = re.compile(r"1:([0-9]+):ios:[0-9a-f]+")
PROJECT_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{4,61}[a-z0-9]")
ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,127}")


class ConfigError(RuntimeError):
    """Stable internal failure that never contains configuration values."""


def request_json(url: str, *, access_token: str, quota_project: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-goog-user-project": quota_project,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
        raise ConfigError("firebase request failed") from error
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ConfigError("firebase response too large")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ConfigError("firebase response invalid") from error
    if not isinstance(value, dict):
        raise ConfigError("firebase response invalid")
    return value


def select_app_name(
    payload: dict[str, Any],
    *,
    bundle_id: str,
    expected_app_id: str,
) -> str:
    apps = payload.get("apps")
    if not isinstance(apps, list):
        raise ConfigError("firebase app list invalid")
    matches = [
        app
        for app in apps
        if isinstance(app, dict)
        and app.get("bundleId") == bundle_id
        and app.get("appId") == expected_app_id
        and app.get("state") == "ACTIVE"
    ]
    if len(matches) != 1:
        raise ConfigError("firebase app identity mismatch")
    name = matches[0].get("name")
    if (
        not isinstance(name, str)
        or re.fullmatch(
            r"projects/[a-z0-9-]+/iosApps/" + re.escape(expected_app_id),
            name,
        )
        is None
    ):
        raise ConfigError("firebase app resource invalid")
    return name


def validate_config(
    payload: bytes,
    *,
    bundle_id: str,
    expected_app_id: str,
    project_id: str,
) -> bytes:
    try:
        config = plistlib.loads(payload)
    except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError) as error:
        raise ConfigError("firebase plist invalid") from error
    if not isinstance(config, dict):
        raise ConfigError("firebase plist invalid")
    app_id = config.get("GOOGLE_APP_ID")
    sender_id = config.get("GCM_SENDER_ID")
    required = (
        config.get("API_KEY"),
        config.get("PROJECT_ID"),
        sender_id,
        app_id,
    )
    if any(not isinstance(value, str) or not value for value in required):
        raise ConfigError("firebase plist incomplete")
    app_id_match = APP_ID_PATTERN.fullmatch(app_id)
    if (
        app_id_match is None
        or app_id_match.group(1) != sender_id
        or app_id != expected_app_id
        or config.get("BUNDLE_ID") != bundle_id
        or config.get("PROJECT_ID") != project_id
    ):
        raise ConfigError("firebase plist identity mismatch")
    return payload


def write_config(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=".firebase-ios-config.",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
        destination.chmod(0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def install_from_environment(
    *,
    environment: Mapping[str, str],
    variable: str,
    project_id: str,
    expected_app_id: str,
    bundle_id: str,
    destination: Path,
) -> None:
    if ENVIRONMENT_VARIABLE_PATTERN.fullmatch(variable) is None:
        raise ConfigError("firebase environment variable invalid")
    encoded = environment.get(variable)
    maximum_encoded_bytes = ((MAX_RESPONSE_BYTES + 2) // 3) * 4
    if (
        not isinstance(encoded, str)
        or not encoded
        or len(encoded) > maximum_encoded_bytes
    ):
        raise ConfigError("firebase environment configuration missing")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ConfigError("firebase environment configuration invalid") from error
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ConfigError("firebase environment configuration too large")
    validated = validate_config(
        payload,
        bundle_id=bundle_id,
        expected_app_id=expected_app_id,
        project_id=project_id,
    )
    write_config(destination, validated)


def access_token(project_id: str) -> str:
    try:
        result = subprocess.run(
            [
                "gcloud",
                "auth",
                "print-access-token",
                f"--project={project_id}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ConfigError("gcloud authentication failed") from error
    token = result.stdout.strip()
    if not 20 <= len(token) <= 4096 or re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token) is None:
        raise ConfigError("gcloud authentication invalid")
    return token


def install(
    *,
    project_id: str,
    expected_app_id: str,
    bundle_id: str,
    destination: Path,
) -> None:
    if PROJECT_ID_PATTERN.fullmatch(project_id) is None:
        raise ConfigError("project identity invalid")
    if APP_ID_PATTERN.fullmatch(expected_app_id) is None:
        raise ConfigError("app identity invalid")
    token = access_token(project_id)
    apps = request_json(
        f"https://firebase.googleapis.com/v1beta1/projects/"
        f"{urllib.parse.quote(project_id, safe='')}/iosApps",
        access_token=token,
        quota_project=project_id,
    )
    app_name = select_app_name(
        apps,
        bundle_id=bundle_id,
        expected_app_id=expected_app_id,
    )
    config_response = request_json(
        f"https://firebase.googleapis.com/v1beta1/"
        f"{urllib.parse.quote(app_name, safe='/')}/config",
        access_token=token,
        quota_project=project_id,
    )
    encoded = config_response.get("configFileContents")
    if not isinstance(encoded, str):
        raise ConfigError("firebase config response invalid")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ConfigError("firebase config response invalid") from error
    validated = validate_config(
        payload,
        bundle_id=bundle_id,
        expected_app_id=expected_app_id,
        project_id=project_id,
    )
    write_config(destination, validated)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the exact Firebase iOS client configuration"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--expected-app-id", required=True)
    parser.add_argument("--bundle-id", default="com.zll.sumaiguard")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument(
        "--config-base64-env",
        help="Read base64-encoded client configuration from this environment variable",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.config_base64_env:
            install_from_environment(
                environment=os.environ,
                variable=args.config_base64_env,
                project_id=args.project,
                expected_app_id=args.expected_app_id,
                bundle_id=args.bundle_id,
                destination=args.destination,
            )
        else:
            install(
                project_id=args.project,
                expected_app_id=args.expected_app_id,
                bundle_id=args.bundle_id,
                destination=args.destination,
            )
    except ConfigError:
        print("firebase_ios_config=FAILED", file=sys.stderr)
        return 1
    print("firebase_ios_config=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

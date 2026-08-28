#!/usr/bin/env python3
"""Fail-closed validation for the SumaiGuard iOS release configuration.

Diagnostics intentionally contain only stable rule codes, repository-relative
paths, and fixed rule descriptions. Parsed values are never echoed.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import plistlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from PIL import Image, UnidentifiedImageError


EXPECTED = {
    "target": "SumaiGuard",
    "bundle": "com.zll.sumaiguard",
    "display_name": "実家チェック",
    "name": "実家あんしんチェック",
    "version": "1.0",
    "build": "3",
    "team": "YMUG864233",
    "deployment": "17.0",
    "device_family": "1",
    "firebase": "12.17.0",
    "app_icon": "AppIcon",
}

PATHS = {
    "project": "ios/project.yml",
    "info": "ios/SumaiGuard/Info.plist",
    "entitlements": "ios/SumaiGuard/SumaiGuard.entitlements",
    "release": "ios/SumaiGuard/Config/Release.xcconfig",
    "sources": "ios/SumaiGuard/**/*.swift",
    "pbx": "ios/SumaiGuard.xcodeproj/project.pbxproj",
    "resolved": (
        "ios/SumaiGuard.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/"
        "Package.resolved"
    ),
    "firebase_config": (
        "ios/SumaiGuard/Resources/GoogleService-Info.plist"
    ),
    "icon": "ios/SumaiGuard/Resources/Assets.xcassets/AppIcon.appiconset",
}

RULES = {
    "INPUT_FILE_MISSING": "required release input is missing",
    "INPUT_PARSE_FAILED": "required release input could not be parsed safely",
    "ICON_ASSET_MISSING": "AppIcon asset catalog entry is missing",
    "ICON_MARKETING_ENTRY_MISSING": "AppIcon has no 1024-point marketing entry",
    "ICON_FILE_MISSING": "AppIcon references a missing image",
    "ICON_FORMAT_INVALID": "AppIcon image must be PNG",
    "ICON_SIZE_INVALID": "App Store icon must be exactly 1024 by 1024 pixels",
    "ICON_RENDITION_SIZE_INVALID": "AppIcon rendition dimensions do not match metadata",
    "ICON_ALPHA_CHANNEL": "AppIcon images must not contain an alpha channel",
    "ICON_TRANSPARENT": "AppIcon images must not contain transparent pixels",
    "APP_ATTEST_NOT_PRODUCTION": "App Attest entitlement must be production",
    "APP_ATTEST_ENTITLEMENTS_UNBOUND": (
        "Release must bind the production App Attest entitlement file"
    ),
    "RELEASE_DEBUG_PROVIDER": "Release-compiled source contains the App Check debug provider",
    "RELEASE_DEBUG_TOKEN": "Release source or settings contain a debug-token marker",
    "API_ORIGIN_MISSING": "Release API origin is missing",
    "API_ORIGIN_INVALID": "Release API origin must be a host-only HTTPS origin",
    "API_ORIGIN_LOOPBACK": "Release API origin must not be loopback",
    "API_ORIGIN_PLACEHOLDER": "Release API origin must not use an invalid placeholder",
    "API_ORIGIN_CLEARTEXT": "Release API origin must use HTTPS",
    "RELEASE_CLEARTEXT_URL": "Release-compiled source contains a cleartext URL",
    "RELEASE_LOOPBACK_URL": "Release-compiled source contains a loopback URL",
    "RELEASE_INVALID_URL": "Release-compiled source contains an invalid placeholder URL",
    "IDENTITY_BUNDLE_MISMATCH": "bundle identifier is inconsistent",
    "IDENTITY_DISPLAY_NAME_MISMATCH": "home-screen display name is inconsistent",
    "IDENTITY_NAME_MISMATCH": "public product name is inconsistent",
    "IDENTITY_VERSION_MISMATCH": "marketing version is inconsistent",
    "IDENTITY_BUILD_MISMATCH": "build number is inconsistent",
    "IDENTITY_APPICON_MISMATCH": "AppIcon build setting is inconsistent",
    "CLOUD_SIGNING_MISMATCH": (
        "Xcode Cloud targets must use the release team with automatic signing"
    ),
    "DEVICE_FAMILY_NOT_IPHONE_ONLY": "target must be iPhone only",
    "DEPLOYMENT_TARGET_TOO_LOW": "deployment target must be iOS 17 or later",
    "FIREBASE_NOT_EXACTLY_PINNED": "Firebase dependency must use exactVersion",
    "FIREBASE_PIN_MISMATCH": "Firebase pins are inconsistent",
    "FIREBASE_CONFIG_MISSING": "Firebase iOS client configuration is missing",
    "FIREBASE_CONFIG_INVALID": "Firebase iOS client configuration is invalid",
    "FIREBASE_CONFIG_IDENTITY_MISMATCH": (
        "Firebase iOS client configuration does not match the release identity"
    ),
}

MAX_TEXT_BYTES = 8 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 32 * 1024 * 1024


@dataclass(frozen=True, order=True)
class Finding:
    code: str
    path: str

    def render(self) -> str:
        return f"ERROR {self.code} {self.path} {RULES[self.code]}"


class Validator:
    def __init__(
        self,
        root: Path,
        *,
        allow_invalid_api_origin_for_ci: bool,
        allow_missing_firebase_config_for_ci: bool,
        expected_firebase_app_id: str,
    ) -> None:
        self.root = root.resolve()
        self.allow_invalid_api_origin_for_ci = allow_invalid_api_origin_for_ci
        self.allow_missing_firebase_config_for_ci = (
            allow_missing_firebase_config_for_ci
        )
        self.expected_firebase_app_id = expected_firebase_app_id
        self.findings: set[Finding] = set()

    def add(self, code: str, path_key: str) -> None:
        self.findings.add(Finding(code, PATHS[path_key]))

    def file(self, path_key: str) -> Path:
        return self.root / PATHS[path_key]

    def read_bytes(self, path_key: str) -> bytes | None:
        path = self.file(path_key)
        try:
            payload = path.read_bytes()
        except OSError:
            self.add("INPUT_FILE_MISSING", path_key)
            return None
        if len(payload) > MAX_TEXT_BYTES:
            self.add("INPUT_PARSE_FAILED", path_key)
            return None
        return payload

    def read_text(self, path_key: str) -> str | None:
        payload = self.read_bytes(path_key)
        if payload is None:
            return None
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            self.add("INPUT_PARSE_FAILED", path_key)
            return None

    def read_yaml(self, path_key: str) -> dict[str, Any] | None:
        text = self.read_text(path_key)
        if text is None:
            return None
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError:
            self.add("INPUT_PARSE_FAILED", path_key)
            return None
        if not isinstance(value, dict):
            self.add("INPUT_PARSE_FAILED", path_key)
            return None
        return value

    def read_plist(self, path_key: str) -> dict[str, Any] | None:
        payload = self.read_bytes(path_key)
        if payload is None:
            return None
        try:
            value = plistlib.loads(payload)
        except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError):
            self.add("INPUT_PARSE_FAILED", path_key)
            return None
        if not isinstance(value, dict):
            self.add("INPUT_PARSE_FAILED", path_key)
            return None
        return value

    def read_json_path(self, path: Path, path_key: str) -> dict[str, Any] | None:
        try:
            payload = path.read_bytes()
            if len(payload) > MAX_TEXT_BYTES:
                raise ValueError
            value = json.loads(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            self.add("INPUT_PARSE_FAILED", path_key)
            return None
        if not isinstance(value, dict):
            self.add("INPUT_PARSE_FAILED", path_key)
            return None
        return value

    def run(self) -> list[Finding]:
        project = self.read_yaml("project")
        info = self.read_plist("info")
        entitlements = self.read_plist("entitlements")
        pbx = self.read_text("pbx")
        resolved = self.read_json_path(self.file("resolved"), "resolved")
        release = self.read_text("release")

        self.validate_project_identity(project, info, pbx)
        self.validate_cloud_signing(project, pbx)
        self.validate_project_entitlements_binding(project)
        self.validate_entitlements(entitlements)
        self.validate_firebase(project, pbx, resolved)
        self.validate_firebase_client_config()
        self.validate_release_settings(release)
        self.validate_release_sources()
        self.validate_icons()
        return sorted(self.findings)

    def validate_project_identity(
        self,
        project: dict[str, Any] | None,
        info: dict[str, Any] | None,
        pbx: str | None,
    ) -> None:
        if project is None or info is None or pbx is None:
            return
        targets = project.get("targets")
        app = targets.get(EXPECTED["target"]) if isinstance(targets, dict) else None
        if not isinstance(app, dict):
            self.add("IDENTITY_BUNDLE_MISMATCH", "project")
            return
        settings = app.get("settings")
        base = settings.get("base") if isinstance(settings, dict) else None
        if not isinstance(base, dict):
            self.add("IDENTITY_BUNDLE_MISMATCH", "project")
            return

        project_bundle = str(base.get("PRODUCT_BUNDLE_IDENTIFIER", ""))
        project_version = str(base.get("MARKETING_VERSION", ""))
        project_build = str(base.get("CURRENT_PROJECT_VERSION", ""))
        project_family = str(base.get("TARGETED_DEVICE_FAMILY", ""))
        project_icon = str(base.get("ASSETCATALOG_COMPILER_APPICON_NAME", ""))
        deployment = str(app.get("deploymentTarget", ""))

        if project_bundle != EXPECTED["bundle"]:
            self.add("IDENTITY_BUNDLE_MISMATCH", "project")
        if project_version != EXPECTED["version"]:
            self.add("IDENTITY_VERSION_MISMATCH", "project")
        if project_build != EXPECTED["build"]:
            self.add("IDENTITY_BUILD_MISMATCH", "project")
        if project_family != EXPECTED["device_family"]:
            self.add("DEVICE_FAMILY_NOT_IPHONE_ONLY", "project")
        if project_icon != EXPECTED["app_icon"]:
            self.add("IDENTITY_APPICON_MISMATCH", "project")
        if not self.version_at_least(deployment, EXPECTED["deployment"]):
            self.add("DEPLOYMENT_TARGET_TOO_LOW", "project")

        if info.get("CFBundleDisplayName") != EXPECTED["display_name"]:
            self.add("IDENTITY_DISPLAY_NAME_MISMATCH", "info")
        if info.get("CFBundleName") != EXPECTED["name"]:
            self.add("IDENTITY_NAME_MISMATCH", "info")
        if info.get("CFBundleIdentifier") not in {
            "$(PRODUCT_BUNDLE_IDENTIFIER)",
            project_bundle,
        }:
            self.add("IDENTITY_BUNDLE_MISMATCH", "info")
        if info.get("CFBundleShortVersionString") not in {
            "$(MARKETING_VERSION)",
            project_version,
        }:
            self.add("IDENTITY_VERSION_MISMATCH", "info")
        if str(info.get("CFBundleVersion", "")) not in {
            "$(CURRENT_PROJECT_VERSION)",
            project_build,
        }:
            self.add("IDENTITY_BUILD_MISMATCH", "info")

        self.validate_pbx_setting(
            pbx,
            "PRODUCT_BUNDLE_IDENTIFIER",
            project_bundle,
            "IDENTITY_BUNDLE_MISMATCH",
            allow_test_suffix=True,
        )
        self.validate_pbx_setting(
            pbx,
            "MARKETING_VERSION",
            project_version,
            "IDENTITY_VERSION_MISMATCH",
        )
        self.validate_pbx_setting(
            pbx,
            "CURRENT_PROJECT_VERSION",
            project_build,
            "IDENTITY_BUILD_MISMATCH",
        )
        self.validate_pbx_setting(
            pbx,
            "TARGETED_DEVICE_FAMILY",
            EXPECTED["device_family"],
            "DEVICE_FAMILY_NOT_IPHONE_ONLY",
        )
        self.validate_pbx_setting(
            pbx,
            "ASSETCATALOG_COMPILER_APPICON_NAME",
            EXPECTED["app_icon"],
            "IDENTITY_APPICON_MISMATCH",
        )
        deployment_values = self.pbx_values(pbx, "IPHONEOS_DEPLOYMENT_TARGET")
        if not deployment_values or any(
            not self.version_at_least(value, EXPECTED["deployment"])
            for value in deployment_values
        ):
            self.add("DEPLOYMENT_TARGET_TOO_LOW", "pbx")
        if "productName = SumaiGuard;" not in pbx:
            self.add("IDENTITY_NAME_MISMATCH", "pbx")

    def validate_cloud_signing(
        self,
        project: dict[str, Any] | None,
        pbx: str | None,
    ) -> None:
        if project is not None:
            targets = project.get("targets")
            signing_valid = isinstance(targets, dict)
            for target_name in (EXPECTED["target"], f'{EXPECTED["target"]}Tests'):
                target = targets.get(target_name) if isinstance(targets, dict) else None
                settings = target.get("settings") if isinstance(target, dict) else None
                base = settings.get("base") if isinstance(settings, dict) else None
                if not isinstance(base, dict) or (
                    str(base.get("DEVELOPMENT_TEAM", "")) != EXPECTED["team"]
                    or str(base.get("CODE_SIGN_STYLE", "")) != "Automatic"
                ):
                    signing_valid = False
            if not signing_valid:
                self.add("CLOUD_SIGNING_MISMATCH", "project")

        if pbx is not None:
            team_values = self.pbx_values(pbx, "DEVELOPMENT_TEAM")
            style_values = self.pbx_values(pbx, "CODE_SIGN_STYLE")
            target_teams = re.findall(
                r"^\s*DevelopmentTeam\s*=\s*([^;]+);",
                pbx,
                flags=re.MULTILINE,
            )
            provisioning_styles = re.findall(
                r"^\s*ProvisioningStyle\s*=\s*([^;]+);",
                pbx,
                flags=re.MULTILINE,
            )
            if (
                not team_values
                or any(value != EXPECTED["team"] for value in team_values)
                or not style_values
                or any(value != "Automatic" for value in style_values)
                or len(target_teams) != 2
                or any(value.strip() != EXPECTED["team"] for value in target_teams)
                or len(provisioning_styles) != 2
                or any(value.strip() != "Automatic" for value in provisioning_styles)
            ):
                self.add("CLOUD_SIGNING_MISMATCH", "pbx")

    def validate_pbx_setting(
        self,
        pbx: str,
        key: str,
        expected: str,
        code: str,
        *,
        allow_test_suffix: bool = False,
    ) -> None:
        values = self.pbx_values(pbx, key)
        if allow_test_suffix:
            values = [value for value in values if not value.endswith(".tests")]
        if not values or any(value != expected for value in values):
            self.add(code, "pbx")

    @staticmethod
    def pbx_values(pbx: str, key: str) -> list[str]:
        pattern = rf"^\s*{re.escape(key)}\s*=\s*\"?([^\";]+)\"?;"
        return [match.strip() for match in re.findall(pattern, pbx, flags=re.MULTILINE)]

    @staticmethod
    def version_at_least(value: str, minimum: str) -> bool:
        try:
            current_parts = tuple(int(part) for part in value.split("."))
            minimum_parts = tuple(int(part) for part in minimum.split("."))
        except (ValueError, AttributeError):
            return False
        length = max(len(current_parts), len(minimum_parts))
        return current_parts + (0,) * (length - len(current_parts)) >= (
            minimum_parts + (0,) * (length - len(minimum_parts))
        )

    def validate_entitlements(self, entitlements: dict[str, Any] | None) -> None:
        if entitlements is None:
            return
        if (
            entitlements.get("com.apple.developer.devicecheck.appattest-environment")
            != "production"
        ):
            self.add("APP_ATTEST_NOT_PRODUCTION", "entitlements")

    def validate_project_entitlements_binding(
        self,
        project: dict[str, Any] | None,
    ) -> None:
        if project is None:
            return
        targets = project.get("targets")
        app = targets.get(EXPECTED["target"]) if isinstance(targets, dict) else None
        config_files = app.get("configFiles") if isinstance(app, dict) else None
        if not isinstance(config_files, dict) or (
            config_files.get("Release") != "SumaiGuard/Config/Release.xcconfig"
        ):
            self.add("APP_ATTEST_ENTITLEMENTS_UNBOUND", "project")

    def validate_firebase(
        self,
        project: dict[str, Any] | None,
        pbx: str | None,
        resolved: dict[str, Any] | None,
    ) -> None:
        if project is None:
            return
        packages = project.get("packages")
        firebase = packages.get("Firebase") if isinstance(packages, dict) else None
        exact = firebase.get("exactVersion") if isinstance(firebase, dict) else None
        if str(exact or "") != EXPECTED["firebase"] or (
            isinstance(firebase, dict) and set(firebase).intersection({"from", "branch", "revision"})
        ):
            self.add("FIREBASE_NOT_EXACTLY_PINNED", "project")

        if pbx is not None:
            exact_block = re.search(
                r'repositoryURL\s*=\s*"https://github\.com/firebase/firebase-ios-sdk\.git";'
                r".*?requirement\s*=\s*\{.*?kind\s*=\s*exactVersion;"
                r".*?version\s*=\s*([^;]+);",
                pbx,
                flags=re.DOTALL,
            )
            if exact_block is None or exact_block.group(1).strip() != EXPECTED["firebase"]:
                self.add("FIREBASE_PIN_MISMATCH", "pbx")

        if resolved is not None:
            pins = resolved.get("pins")
            firebase_pins = [
                pin
                for pin in pins if isinstance(pin, dict) and pin.get("identity") == "firebase-ios-sdk"
            ] if isinstance(pins, list) else []
            if len(firebase_pins) != 1:
                self.add("FIREBASE_PIN_MISMATCH", "resolved")
            else:
                state = firebase_pins[0].get("state")
                if not isinstance(state, dict) or (
                    state.get("version") != EXPECTED["firebase"]
                    or re.fullmatch(r"[0-9a-f]{40}", str(state.get("revision", ""))) is None
                ):
                    self.add("FIREBASE_PIN_MISMATCH", "resolved")

    def validate_firebase_client_config(self) -> None:
        config_path = self.file("firebase_config")
        try:
            payload = config_path.read_bytes()
        except FileNotFoundError:
            if not self.allow_missing_firebase_config_for_ci:
                self.add("FIREBASE_CONFIG_MISSING", "firebase_config")
            return
        except OSError:
            self.add("FIREBASE_CONFIG_INVALID", "firebase_config")
            return
        if not payload or len(payload) > MAX_TEXT_BYTES:
            self.add("FIREBASE_CONFIG_INVALID", "firebase_config")
            return
        try:
            config = plistlib.loads(payload)
        except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError):
            self.add("FIREBASE_CONFIG_INVALID", "firebase_config")
            return
        if not isinstance(config, dict):
            self.add("FIREBASE_CONFIG_INVALID", "firebase_config")
            return

        app_id = config.get("GOOGLE_APP_ID")
        sender_id = config.get("GCM_SENDER_ID")
        required_strings = (
            config.get("API_KEY"),
            config.get("PROJECT_ID"),
            sender_id,
            app_id,
        )
        if any(not isinstance(value, str) or not value for value in required_strings):
            self.add("FIREBASE_CONFIG_INVALID", "firebase_config")
            return
        app_id_match = re.fullmatch(r"1:([0-9]+):ios:[0-9a-f]+", app_id)
        if app_id_match is None or app_id_match.group(1) != sender_id:
            self.add("FIREBASE_CONFIG_INVALID", "firebase_config")
            return
        if (
            config.get("BUNDLE_ID") != EXPECTED["bundle"]
            or not self.expected_firebase_app_id
            or app_id != self.expected_firebase_app_id
        ):
            self.add("FIREBASE_CONFIG_IDENTITY_MISMATCH", "firebase_config")

    def validate_release_settings(self, release: str | None) -> None:
        if release is None:
            return
        if "FIRAppCheckDebugToken" in release:
            self.add("RELEASE_DEBUG_TOKEN", "release")
        assignments: dict[str, str] = {}
        for raw_line in release.splitlines():
            line = raw_line.split("//", 1)[0].strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            assignments[key.strip()] = value.strip()
        if (
            assignments.get("CODE_SIGN_ENTITLEMENTS")
            != "SumaiGuard/SumaiGuard.entitlements"
        ):
            self.add("APP_ATTEST_ENTITLEMENTS_UNBOUND", "release")
        raw_origin = assignments.get("SUMAI_API_ORIGIN")
        if not raw_origin:
            self.add("API_ORIGIN_MISSING", "release")
            return
        origin = raw_origin.replace("$()", "")
        self.validate_origin(origin)

    def validate_origin(self, origin: str) -> None:
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError:
            self.add("API_ORIGIN_INVALID", "release")
            return
        if parsed.scheme.lower() == "http":
            self.add("API_ORIGIN_CLEARTEXT", "release")
        elif parsed.scheme.lower() != "https":
            self.add("API_ORIGIN_INVALID", "release")
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            self.add("API_ORIGIN_INVALID", "release")
            return
        host = parsed.hostname.lower()
        if self.is_loopback(host):
            self.add("API_ORIGIN_LOOPBACK", "release")
        if host == "invalid.invalid":
            if not self.allow_invalid_api_origin_for_ci:
                self.add("API_ORIGIN_PLACEHOLDER", "release")
        elif host.endswith(".invalid") or host == "invalid":
            self.add("API_ORIGIN_PLACEHOLDER", "release")

    @staticmethod
    def is_loopback(host: str) -> bool:
        if host == "localhost" or host.endswith(".localhost"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def validate_release_sources(self) -> None:
        source_root = self.root / "ios" / "SumaiGuard"
        try:
            sources = sorted(source_root.rglob("*.swift"))
        except OSError:
            self.add("INPUT_FILE_MISSING", "sources")
            return
        if not sources:
            self.add("INPUT_FILE_MISSING", "sources")
            return
        for source in sources:
            try:
                if source.stat().st_size > MAX_TEXT_BYTES:
                    raise ValueError
                text = source.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, ValueError):
                self.add("INPUT_PARSE_FAILED", "sources")
                continue
            for line in self.release_active_lines(text):
                code = self.strip_swift_line_comment(line)
                if "AppCheckDebugProviderFactory" in code:
                    self.add("RELEASE_DEBUG_PROVIDER", "sources")
                if "FIRAppCheckDebugToken" in code:
                    self.add("RELEASE_DEBUG_TOKEN", "sources")
                for url in re.findall(r'https?://[^\s"\']+', code):
                    parsed = urlsplit(url)
                    if parsed.scheme == "http":
                        self.add("RELEASE_CLEARTEXT_URL", "sources")
                    if parsed.hostname and self.is_loopback(parsed.hostname.lower()):
                        self.add("RELEASE_LOOPBACK_URL", "sources")
                    if parsed.hostname and (
                        parsed.hostname.lower() == "invalid"
                        or parsed.hostname.lower().endswith(".invalid")
                    ):
                        self.add("RELEASE_INVALID_URL", "sources")

    @staticmethod
    def strip_swift_line_comment(line: str) -> str:
        in_string = False
        escaped = False
        index = 0
        while index < len(line):
            character = line[index]
            if escaped:
                escaped = False
            elif character == "\\" and in_string:
                escaped = True
            elif character == '"':
                in_string = not in_string
            elif character == "/" and not in_string and line[index:index + 2] == "//":
                return line[:index]
            index += 1
        return line

    @staticmethod
    def release_active_lines(text: str) -> list[str]:
        active = True
        stack: list[tuple[bool, bool]] = []
        result: list[str] = []
        for line in text.splitlines():
            directive = line.strip()
            if directive.startswith("#if "):
                condition = directive[4:].strip()
                condition_active = condition in {"!DEBUG", "not DEBUG"} or condition != "DEBUG"
                stack.append((active, condition_active))
                active = active and condition_active
                continue
            if directive.startswith("#elseif "):
                if stack:
                    parent, first_condition = stack[-1]
                    condition = directive[8:].strip()
                    condition_active = condition in {"!DEBUG", "not DEBUG"} or condition != "DEBUG"
                    active = parent and not first_condition and condition_active
                continue
            if directive == "#else":
                if stack:
                    parent, first_condition = stack[-1]
                    active = parent and not first_condition
                continue
            if directive == "#endif":
                if stack:
                    parent, _ = stack.pop()
                    active = parent
                continue
            if active:
                result.append(line)
        return result

    def validate_icons(self) -> None:
        icon_root = self.file("icon")
        contents_path = icon_root / "Contents.json"
        if not icon_root.is_dir() or not contents_path.is_file():
            self.add("ICON_ASSET_MISSING", "icon")
            return
        contents = self.read_json_path(contents_path, "icon")
        if contents is None:
            return
        images = contents.get("images")
        if not isinstance(images, list):
            self.add("INPUT_PARSE_FAILED", "icon")
            return
        marketing_found = False
        for entry in images:
            if not isinstance(entry, dict):
                self.add("INPUT_PARSE_FAILED", "icon")
                continue
            filename = entry.get("filename")
            size_text = entry.get("size")
            scale_text = entry.get("scale")
            if not isinstance(filename, str) or Path(filename).name != filename:
                self.add("ICON_FILE_MISSING", "icon")
                continue
            if entry.get("idiom") == "ios-marketing" and size_text == "1024x1024" and scale_text == "1x":
                marketing_found = True
            expected_pixels = self.icon_pixel_size(size_text, scale_text)
            image_path = icon_root / filename
            if not image_path.is_file():
                self.add("ICON_FILE_MISSING", "icon")
                continue
            self.validate_icon_file(image_path, expected_pixels, marketing=(entry.get("idiom") == "ios-marketing"))
        if not marketing_found:
            self.add("ICON_MARKETING_ENTRY_MISSING", "icon")

    @staticmethod
    def icon_pixel_size(size_text: Any, scale_text: Any) -> tuple[int, int] | None:
        if not isinstance(size_text, str) or not isinstance(scale_text, str):
            return None
        size_match = re.fullmatch(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)", size_text)
        scale_match = re.fullmatch(r"(\d+)x", scale_text)
        if size_match is None or scale_match is None:
            return None
        scale = int(scale_match.group(1))
        width = float(size_match.group(1)) * scale
        height = float(size_match.group(2)) * scale
        if not width.is_integer() or not height.is_integer():
            return None
        return int(width), int(height)

    def validate_icon_file(
        self,
        image_path: Path,
        expected_pixels: tuple[int, int] | None,
        *,
        marketing: bool,
    ) -> None:
        try:
            with Image.open(image_path) as image:
                image.load()
                if image.format != "PNG":
                    self.add("ICON_FORMAT_INVALID", "icon")
                if expected_pixels is None or image.size != expected_pixels:
                    self.add(
                        "ICON_SIZE_INVALID" if marketing else "ICON_RENDITION_SIZE_INVALID",
                        "icon",
                    )
                if marketing and image.size != (1024, 1024):
                    self.add("ICON_SIZE_INVALID", "icon")
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                if has_alpha:
                    self.add("ICON_ALPHA_CHANNEL", "icon")
                    alpha = image.convert("RGBA").getchannel("A")
                    if alpha.getextrema()[0] < 255:
                        self.add("ICON_TRANSPARENT", "icon")
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            self.add("ICON_FORMAT_INVALID", "icon")


def validate_repository(
    root: Path,
    *,
    allow_invalid_api_origin_for_ci: bool = False,
    allow_missing_firebase_config_for_ci: bool = False,
    expected_firebase_app_id: str = "",
) -> list[Finding]:
    return Validator(
        root,
        allow_invalid_api_origin_for_ci=allow_invalid_api_origin_for_ci,
        allow_missing_firebase_config_for_ci=(
            allow_missing_firebase_config_for_ci
        ),
        expected_firebase_app_id=expected_firebase_app_id,
    ).run()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate SumaiGuard iOS release inputs")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--allow-invalid-api-origin-for-ci",
        action="store_true",
        help="Allow only the committed invalid.invalid API-origin placeholder for CI",
    )
    parser.add_argument(
        "--allow-missing-firebase-config-for-ci",
        action="store_true",
        help=(
            "Allow only the untracked Firebase client configuration to be "
            "absent in CI"
        ),
    )
    parser.add_argument(
        "--expected-firebase-app-id",
        default="",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        findings = validate_repository(
            args.root,
            allow_invalid_api_origin_for_ci=args.allow_invalid_api_origin_for_ci,
            allow_missing_firebase_config_for_ci=(
                args.allow_missing_firebase_config_for_ci
            ),
            expected_firebase_app_id=args.expected_firebase_app_id,
        )
    except Exception:
        findings = [Finding("INPUT_PARSE_FAILED", PATHS["project"])]
    if findings:
        for finding in findings:
            print(finding.render())
        return 1
    print("PASS IOS_RELEASE_VALIDATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

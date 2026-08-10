from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ENTRY = ROOT / "ios" / "SumaiGuard" / "App" / "SumaiGuardApp.swift"
HARNESS = (
    ROOT
    / "ios"
    / "SumaiGuard"
    / "App"
    / "AppStoreScreenshotRoot.swift"
)


def test_screenshot_harness_is_debug_only_and_uses_exact_five_scenes() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert source.lstrip().startswith("#if DEBUG")
    assert source.rstrip().endswith("#endif")
    assert "SUMAI_SCREENSHOT_SCENE" in source
    assert {
        "capture",
        "visibleRisks",
        "actionTiers",
        "consent",
        "sharePDF",
    } <= set(source.split())
    assert "架空" in source
    assert "URLSession" not in source
    assert "APIClient" not in source
    assert re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", source) is None


def test_app_entry_routes_to_harness_only_in_debug_builds() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    debug_start = source.index("#if DEBUG")
    screenshot_route = source.index("AppStoreScreenshotRoot")
    debug_end = source.index("#endif", screenshot_route)
    assert debug_start < screenshot_route < debug_end
    assert source.count("AppStoreScreenshotRoot") == 1

#!/usr/bin/env python3
"""Fail-closed validation for the Japanese App Store screenshot set."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path

from PIL import Image, ImageStat, UnidentifiedImageError


FILENAMES = (
    "01-capture.png",
    "02-visible-risks.png",
    "03-action-tiers.png",
    "04-consent.png",
    "05-share-pdf.png",
)
HEADLINES = (
    "親の家、気になったら 写真を1枚",
    "見える注意点だけ 赤枠で確認",
    "次にできることを 3つの相談先へ",
    "送るたびに 確認してから",
    "写真を入れずに 相談用PDFへ",
)

# Apple App Store Connect screenshot specifications observed 2026-08-10.
ALLOWED_69_INCH_PORTRAIT_SIZES = {
    (1260, 2736),
    (1290, 2796),
    (1320, 2868),
}
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_OCR_BYTES = 512 * 1024

PRIVATE_OCR_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?:DEBUG|localhost|127\.0\.0\.1|Bearer\s+|api[_ -]?key|token)", re.I),
    re.compile(r"〒\s*\d{3}-?\d{4}"),
    re.compile(r"(?:東京都|北海道|(?:大阪|京都)府|.{2,3}県).{0,30}(?:市|区|町|村)"),
    re.compile(r"\b[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\b", re.I),
    re.compile(r"(?:緯度|経度|GPS|氏名|住所|電話番号)"),
)


class AssetValidationError(ValueError):
    """A stable release-asset validation failure."""


def _fail(code: str, detail: str = "") -> None:
    suffix = f" {detail}" if detail else ""
    raise AssetValidationError(f"{code}{suffix}")


def _asset_directory(root: Path) -> Path:
    return (
        root
        / "docs"
        / "app-store"
        / "screenshots"
        / "ja-JP"
        / "6.9-inch"
    )


def _validate_manifest(root: Path) -> None:
    path = root / "docs" / "app-store" / "screenshot-plan.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail("MANIFEST_MISSING")
    if not re.search(r"[ぁ-んァ-ン一-龯]", text):
        _fail("MANIFEST_STORY_MISSING")
    for name, headline in zip(FILENAMES, HEADLINES):
        if name not in text or headline not in text:
            _fail("MANIFEST_STORY_MISSING", name)


def _validate_image(path: Path) -> tuple[int, int]:
    try:
        if path.stat().st_size <= 0 or path.stat().st_size > MAX_FILE_BYTES:
            _fail("FILE_SIZE_INVALID", path.name)
        with Image.open(path) as image:
            image.load()
            if image.format != "PNG":
                _fail("FORMAT_INVALID", path.name)
            if image.mode != "RGB":
                _fail("ALPHA_CHANNEL", path.name)
            if image.size not in ALLOWED_69_INCH_PORTRAIT_SIZES:
                _fail("SIZE_INVALID", path.name)
            if image.info or image.getexif():
                _fail("METADATA_PRESENT", path.name)
            sample = image.convert("L").resize((64, 64))
            if ImageStat.Stat(sample).stddev[0] < 1.0:
                _fail("BLANK_ASSET", path.name)
            return image.size
    except AssetValidationError:
        raise
    except (OSError, UnidentifiedImageError, ValueError):
        _fail("IMAGE_INVALID", path.name)


def _ocr_assets(root: Path, paths: list[Path]) -> dict[str, str]:
    script = root / "scripts" / "ocr_app_store_assets.swift"
    if not script.is_file():
        _fail("OCR_RUNNER_MISSING")
    result = subprocess.run(
        ["xcrun", "swift", str(script), *(str(path) for path in paths)],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) > MAX_OCR_BYTES:
        _fail("OCR_FAILED")
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        _fail("OCR_FAILED")
    if not isinstance(payload, dict):
        _fail("OCR_FAILED")
    return payload


def _normalize_story(text: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", text)
        if character.isalnum()
    )


def _validate_ocr(ocr_texts: dict[str, str]) -> None:
    if set(ocr_texts) != set(FILENAMES):
        _fail("OCR_FILE_SET_INVALID")
    for name, headline in zip(FILENAMES, HEADLINES):
        text = ocr_texts.get(name)
        if not isinstance(text, str) or not re.search(r"[ぁ-んァ-ン一-龯]", text):
            _fail("OCR_JAPANESE_MISSING", name)
        if any(pattern.search(text) for pattern in PRIVATE_OCR_PATTERNS):
            _fail("OCR_PRIVATE_CONTENT", name)
        if _normalize_story(headline) not in _normalize_story(text):
            _fail("OCR_HEADLINE_MISSING", name)


def validate_assets(
    root: Path,
    *,
    ocr_texts: dict[str, str] | None = None,
) -> dict[str, object]:
    root = root.resolve()
    directory = _asset_directory(root)
    if not directory.is_dir():
        _fail("DIRECTORY_MISSING")
    entries = sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )
    if entries != sorted(FILENAMES):
        _fail("FILE_SET_INVALID")

    _validate_manifest(root)
    paths = [directory / name for name in FILENAMES]
    sizes = [_validate_image(path) for path in paths]
    if len(set(sizes)) != 1:
        _fail("MIXED_SIZES")

    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    if len(set(hashes)) != len(hashes):
        _fail("DUPLICATE_ASSET")

    observed_ocr = ocr_texts if ocr_texts is not None else _ocr_assets(root, paths)
    _validate_ocr(observed_ocr)
    return {
        "count": len(paths),
        "size": list(sizes[0]),
        "locale": "ja-JP",
        "display": "6.9-inch",
        "hashes": hashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    try:
        report = validate_assets(args.root)
    except AssetValidationError as exc:
        print(f"ERROR APP_STORE_ASSETS {exc}")
        return 1
    width, height = report["size"]
    print(
        "PASS APP_STORE_ASSETS "
        f"count={report['count']} size={width}x{height} "
        f"locale={report['locale']} display={report['display']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

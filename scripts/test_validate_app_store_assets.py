from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, PngImagePlugin


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_app_store_assets.py"
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


def load_validator():
    assert SCRIPT.is_file(), "asset validator must exist"
    spec = importlib.util.spec_from_file_location("validate_app_store_assets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_manifest(root: Path) -> None:
    path = root / "docs" / "app-store" / "screenshot-plan.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"{name} {headline}" for name, headline in zip(FILENAMES, HEADLINES)),
        encoding="utf-8",
    )


def write_images(
    root: Path,
    *,
    size: tuple[int, int] = (1260, 2736),
    mode: str = "RGB",
    duplicate: bool = False,
    metadata: dict[str, str] | None = None,
) -> Path:
    directory = (
        root
        / "docs"
        / "app-store"
        / "screenshots"
        / "ja-JP"
        / "6.9-inch"
    )
    directory.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(FILENAMES):
        color_index = 0 if duplicate else index
        shape_index = 0 if duplicate else index
        base = (235 - color_index * 9, 241 - color_index * 7, 235)
        color = (*base, 255) if mode == "RGBA" else base
        image = Image.new(mode, size, color)
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (80 + shape_index * 5, 120, size[0] - 80, 520 + shape_index * 30),
            fill=(35, 90, 62, 255) if mode == "RGBA" else (35, 90, 62),
        )
        draw.rectangle(
            (120, 700 + shape_index * 40, size[0] - 120, size[1] - 180),
            outline=(181, 139, 50, 255) if mode == "RGBA" else (181, 139, 50),
            width=12,
        )
        pnginfo = None
        if metadata:
            pnginfo = PngImagePlugin.PngInfo()
            for key, value in metadata.items():
                pnginfo.add_text(key, value)
        image.save(directory / name, format="PNG", pnginfo=pnginfo)
    return directory


def safe_ocr() -> dict[str, str]:
    return {
        name: f"実家あんしんチェック {headline}"
        for name, headline in zip(FILENAMES, HEADLINES)
    }


def test_accepts_exact_five_opaque_unique_69_inch_assets(tmp_path: Path) -> None:
    module = load_validator()
    write_manifest(tmp_path)
    write_images(tmp_path)

    report = module.validate_assets(tmp_path, ocr_texts=safe_ocr())

    assert report["count"] == 5
    assert report["size"] == [1260, 2736]
    assert report["locale"] == "ja-JP"
    assert report["display"] == "6.9-inch"


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda root: (root / FILENAMES[-1]).unlink(), "FILE_SET_INVALID"),
        (lambda root: write_images(root.parents[4], mode="RGBA"), "ALPHA_CHANNEL"),
        (
            lambda root: write_images(root.parents[4], size=(1179, 2556)),
            "SIZE_INVALID",
        ),
        (lambda root: write_images(root.parents[4], duplicate=True), "DUPLICATE_ASSET"),
    ],
)
def test_rejects_invalid_file_shape_or_identity(
    tmp_path: Path,
    mutator,
    code: str,
) -> None:
    module = load_validator()
    write_manifest(tmp_path)
    directory = write_images(tmp_path)
    mutator(directory)

    with pytest.raises(module.AssetValidationError, match=code):
        module.validate_assets(tmp_path, ocr_texts=safe_ocr())


def test_rejects_private_or_debug_ocr_text(tmp_path: Path) -> None:
    module = load_validator()
    write_manifest(tmp_path)
    write_images(tmp_path)
    ocr = safe_ocr()
    ocr[FILENAMES[0]] += " DEBUG localhost 〒100-0001"

    with pytest.raises(module.AssetValidationError, match="OCR_PRIVATE_CONTENT"):
        module.validate_assets(tmp_path, ocr_texts=ocr)


def test_rejects_ocr_when_an_asset_does_not_contain_its_headline(
    tmp_path: Path,
) -> None:
    module = load_validator()
    write_manifest(tmp_path)
    write_images(tmp_path)
    ocr = safe_ocr()
    ocr[FILENAMES[2]] = "実家あんしんチェック 別の画面です"

    with pytest.raises(module.AssetValidationError, match="OCR_HEADLINE_MISSING"):
        module.validate_assets(tmp_path, ocr_texts=ocr)


def test_rejects_png_metadata_and_missing_japanese_story(tmp_path: Path) -> None:
    module = load_validator()
    write_manifest(tmp_path)
    write_images(tmp_path, metadata={"Comment": "GPS 35.0,139.0"})

    with pytest.raises(module.AssetValidationError, match="METADATA_PRESENT"):
        module.validate_assets(tmp_path, ocr_texts=safe_ocr())

    (tmp_path / "docs" / "app-store" / "screenshot-plan.md").write_text(
        json.dumps({"files": FILENAMES}),
        encoding="utf-8",
    )
    write_images(tmp_path)

    with pytest.raises(module.AssetValidationError, match="MANIFEST_STORY_MISSING"):
        module.validate_assets(tmp_path, ocr_texts=safe_ocr())

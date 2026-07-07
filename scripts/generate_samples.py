#!/usr/bin/env python3
"""Generate synthetic placeholder sample images for demo purposes.

These are simple geometric illustrations — not copyrighted photographs.
They support the demo layout by giving users something to upload.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "apps" / "sumai_web" / "assets" / "samples"


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc" if bold else "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for path in candidates:
        try:
            p = Path(path)
            if p.exists():
                return ImageFont.truetype(str(p), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def generate_genkan() -> None:
    """Generate a simple genkan (entrance) illustration."""
    img = Image.new("RGB", (800, 600), (245, 241, 232))
    draw = ImageDraw.Draw(img)

    # Floor
    draw.rectangle((0, 350, 800, 600), fill=(220, 210, 195))
    # Step (kamachi)
    draw.rectangle((50, 340, 750, 360), fill=(180, 160, 130))
    draw.rectangle((50, 360, 750, 400), fill=(160, 140, 110))
    # Upper floor
    draw.rectangle((0, 100, 800, 340), fill=(235, 228, 218))
    # Wall
    draw.rectangle((0, 0, 800, 100), fill=(250, 248, 242))
    # Door frame
    draw.rectangle((550, 20, 750, 340), outline=(140, 120, 100), width=3)
    # Shoe area
    draw.rectangle((100, 420, 250, 500), fill=(100, 80, 60), outline=(80, 60, 40), width=2)
    draw.rectangle((280, 430, 400, 510), fill=(90, 70, 55), outline=(70, 50, 35), width=2)
    # Mat
    draw.rectangle((350, 440, 600, 530), fill=(180, 120, 100), outline=(160, 100, 80), width=2)

    # Label
    title_font = _font(28, bold=True)
    draw.text((20, 10), "玄関サンプル（合成画像）", fill=(100, 90, 80), font=title_font)
    small_font = _font(16)
    draw.text((20, 560), "デモ用合成画像 — 著作権なし", fill=(150, 140, 130), font=small_font)

    img.save(OUTPUT_DIR / "genkan_sample.png", optimize=True)
    print(f"Generated: {OUTPUT_DIR / 'genkan_sample.png'}")


def generate_bathroom() -> None:
    """Generate a simple bathroom illustration."""
    img = Image.new("RGB", (800, 600), (230, 238, 240))
    draw = ImageDraw.Draw(img)

    # Floor
    draw.rectangle((0, 350, 800, 600), fill=(200, 210, 215))
    # Tile pattern
    for x in range(0, 800, 80):
        draw.line((x, 350, x, 600), fill=(190, 200, 205), width=1)
    for y in range(350, 600, 80):
        draw.line((0, y, 800, y), fill=(190, 200, 205), width=1)
    # Bathtub
    draw.rounded_rectangle((450, 100, 780, 380), radius=20, fill=(240, 245, 248), outline=(180, 190, 200), width=3)
    draw.rounded_rectangle((460, 110, 770, 370), radius=15, fill=(200, 220, 230), outline=(170, 180, 190), width=2)
    # Wall
    draw.rectangle((0, 0, 800, 100), fill=(245, 248, 250))
    # Shower head
    draw.ellipse((100, 60, 140, 100), fill=(200, 200, 200), outline=(160, 160, 160), width=2)
    draw.line((120, 100, 120, 200), fill=(180, 180, 180), width=3)
    # Drain
    draw.ellipse((350, 480, 390, 520), fill=(170, 175, 180), outline=(150, 155, 160), width=2)

    # Label
    title_font = _font(28, bold=True)
    draw.text((20, 10), "浴室サンプル（合成画像）", fill=(100, 110, 120), font=title_font)
    small_font = _font(16)
    draw.text((20, 560), "デモ用合成画像 — 著作権なし", fill=(150, 160, 170), font=small_font)

    img.save(OUTPUT_DIR / "bathroom_sample.png", optimize=True)
    print(f"Generated: {OUTPUT_DIR / 'bathroom_sample.png'}")


def generate_hallway() -> None:
    """Generate a simple hallway illustration."""
    img = Image.new("RGB", (800, 600), (248, 245, 240))
    draw = ImageDraw.Draw(img)

    # Floor
    draw.rectangle((0, 350, 800, 600), fill=(225, 218, 205))
    # Walls (perspective)
    draw.polygon([(0, 100), (200, 200), (200, 500), (0, 600)], fill=(240, 236, 228))
    draw.polygon([(800, 100), (600, 200), (600, 500), (800, 600)], fill=(240, 236, 228))
    # Floor (perspective)
    draw.polygon([(200, 500), (600, 500), (800, 600), (0, 600)], fill=(225, 218, 205))
    # Ceiling
    draw.polygon([(0, 100), (200, 200), (600, 200), (800, 100)], fill=(250, 248, 244))
    # Cord across floor
    draw.line((150, 480, 650, 460), fill=(60, 60, 60), width=3)
    draw.line((650, 460, 700, 500), fill=(60, 60, 60), width=3)

    # Label
    title_font = _font(28, bold=True)
    draw.text((20, 10), "廊下サンプル（合成画像）", fill=(100, 90, 80), font=title_font)
    small_font = _font(16)
    draw.text((20, 560), "デモ用合成画像 — 著作権なし", fill=(150, 140, 130), font=small_font)

    img.save(OUTPUT_DIR / "hallway_sample.png", optimize=True)
    print(f"Generated: {OUTPUT_DIR / 'hallway_sample.png'}")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generate_genkan()
    generate_bathroom()
    generate_hallway()
    print(f"\nAll samples generated in: {OUTPUT_DIR}")

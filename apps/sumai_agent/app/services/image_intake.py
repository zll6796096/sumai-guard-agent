from __future__ import annotations

import io

from PIL import Image, ImageOps


MAX_DIMENSION = 1600
PREPROCESS_VERSION = "1.0.0"


def read_and_sanitize_image(image_bytes: bytes, max_dimension: int = MAX_DIMENSION) -> tuple[Image.Image, bytes]:
    """Load image bytes, remove metadata, normalize orientation, resize, and return PNG bytes."""
    if not image_bytes:
        raise ValueError("画像ファイルが空です。")

    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except Exception as exc:  # Pillow raises several image-specific exceptions.
        raise ValueError("画像を読み込めませんでした。PNGまたはJPEGを指定してください。") from exc

    image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    safe_png = output.getvalue()

    return image.copy(), safe_png

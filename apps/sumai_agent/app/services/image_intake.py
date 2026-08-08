from __future__ import annotations

import io

from fastapi import UploadFile
from PIL import Image, ImageOps

from app.errors import ImageTooLargeError, InvalidImageError


MAX_DIMENSION = 1600
MAX_SOURCE_PIXELS = 25_000_000
UPLOAD_CHUNK_SIZE = 1024 * 1024
PREPROCESS_VERSION = "1.0.0"


async def read_upload_bytes(
    upload: UploadFile,
    *,
    max_bytes: int,
    chunk_size: int = UPLOAD_CHUNK_SIZE,
) -> bytes:
    """Read an upload in bounded chunks and reject it at the configured limit."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than zero")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    contents = io.BytesIO()
    total = 0
    while True:
        read_size = min(chunk_size, max_bytes - total + 1)
        chunk = await upload.read(read_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ImageTooLargeError
        contents.write(chunk)

    if total == 0:
        raise InvalidImageError
    return contents.getvalue()


def read_and_sanitize_image(
    image_bytes: bytes,
    max_dimension: int = MAX_DIMENSION,
    max_source_pixels: int = MAX_SOURCE_PIXELS,
) -> tuple[Image.Image, bytes]:
    """Load image bytes, remove metadata, normalize orientation, resize, and return PNG bytes."""
    if not image_bytes:
        raise InvalidImageError
    if max_dimension <= 0:
        raise ValueError("max_dimension must be greater than zero")
    if max_source_pixels <= 0:
        raise ValueError("max_source_pixels must be greater than zero")

    image: Image.Image | None = None
    try:
        with io.BytesIO(image_bytes) as source, Image.open(source) as opened:
            width, height = opened.size
            if width * height > max_source_pixels:
                raise ImageTooLargeError
            if opened.format == "JPEG" and max(opened.size) > max_dimension:
                opened.draft("RGB", (max_dimension, max_dimension))
            ImageOps.exif_transpose(opened, in_place=True)
            if opened.mode in {"1", "P"}:
                working = opened.convert("RGB")
                try:
                    working.thumbnail(
                        (max_dimension, max_dimension),
                        Image.Resampling.LANCZOS,
                    )
                    image = working.copy()
                finally:
                    working.close()
            else:
                opened.thumbnail(
                    (max_dimension, max_dimension),
                    Image.Resampling.LANCZOS,
                )
                image = opened.copy() if opened.mode == "RGB" else opened.convert("RGB")
            image.info.clear()

            with io.BytesIO() as output:
                image.save(output, format="PNG", optimize=True)
                safe_png = output.getvalue()
    except ImageTooLargeError:
        if image is not None:
            image.close()
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        if image is not None:
            image.close()
        raise ImageTooLargeError from None
    except Exception:
        if image is not None:
            image.close()
        raise InvalidImageError from None

    assert image is not None
    return image, safe_png

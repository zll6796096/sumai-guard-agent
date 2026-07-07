from __future__ import annotations

import base64
import io

from PIL import Image

from app.models import BoundingBox, RiskFinding
from app.services.visual_renderer import VisualRenderer


def test_visual_renderer_returns_valid_base64_png() -> None:
    image = Image.new("RGB", (640, 480), "white")
    finding = RiskFinding(
        id="R1",
        risk_type="genkan_step",
        label_ja="玄関段差",
        description_ja="段差が見えます。",
        severity=4,
        confidence=0.9,
        bbox=BoundingBox(x=0.2, y=0.3, w=0.4, h=0.25),
        evidence_ja="上がり框の段差が見えます。",
        basis_label_ja="高齢者住宅安全チェックの一般原則",
        basis_summary_ja="段差はつまずきの要因になります。",
        needs_human_confirmation=False,
    )

    annotated, improvement = VisualRenderer().render(image, [finding])

    for encoded in [annotated, improvement]:
        raw = base64.b64decode(encoded)
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        decoded = Image.open(io.BytesIO(raw))
        assert decoded.format == "PNG"
        assert decoded.width > 0
        assert decoded.height > 0

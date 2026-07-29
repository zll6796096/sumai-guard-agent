from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import BoundingBox


@pytest.mark.parametrize(
    "payload",
    [
        {"x": 0.1, "y": 0.1, "w": 0.0, "h": 0.2},
        {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.0},
        {"x": 0.8, "y": 0.1, "w": 0.3, "h": 0.2},
        {"x": 0.1, "y": 0.8, "w": 0.2, "h": 0.3},
    ],
)
def test_bounding_box_rejects_zero_area_and_out_of_frame(payload: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        BoundingBox.model_validate(payload)


def test_bounding_box_accepts_positive_edge_aligned_box() -> None:
    assert BoundingBox(x=0.8, y=0.8, w=0.2, h=0.2)

from __future__ import annotations

import asyncio
import io
from collections.abc import Callable

import pytest
from fastapi import UploadFile
from PIL import Image

from app.models import VisionFacts
from app.services.orchestrator import AnalysisOrchestrator


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class DeterministicVision:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, **_: object) -> tuple[VisionFacts, str]:
        self.calls += 1
        return (
            VisionFacts(
                environment="home",
                room_type="toilet",
                visible_regions=["room"],
                entities=[],
                feature_observations=[],
                relationships=[],
            ),
            "gemini",
        )

    async def aclose(self) -> None:
        return None


@pytest.fixture
def upload_factory() -> Callable[[], UploadFile]:
    return lambda: UploadFile(
        filename="toilet.png",
        file=io.BytesIO(_png_bytes()),
    )


@pytest.mark.asyncio
async def test_orchestrator_emits_real_stages_in_order(
    upload_factory: Callable[[], UploadFile],
) -> None:
    stages: list[str] = []

    async def progress(stage: str) -> None:
        stages.append(stage)

    response = await AnalysisOrchestrator(
        vision=DeterministicVision()  # type: ignore[arg-type]
    ).analyze(
        upload=upload_factory(),
        room_hint="toilet",
        mock=False,
        progress=progress,
    )

    assert response.room_type == "toilet"
    assert stages == ["intake_complete", "vision_complete"]


@pytest.mark.asyncio
async def test_cache_hit_still_reports_intake_and_semantic_readiness(
    upload_factory: Callable[[], UploadFile],
) -> None:
    vision = DeterministicVision()
    orchestrator = AnalysisOrchestrator(vision=vision)  # type: ignore[arg-type]
    await orchestrator.analyze(
        upload=upload_factory(), room_hint="toilet", progress=None
    )
    stages: list[str] = []

    async def progress(stage: str) -> None:
        stages.append(stage)

    response = await orchestrator.analyze(
        upload=upload_factory(), room_hint="toilet", progress=progress
    )

    assert response._cache_hit is True
    assert vision.calls == 1
    assert stages == ["intake_complete", "vision_complete"]


@pytest.mark.asyncio
async def test_coalesced_requests_receive_request_local_stage_events(
    upload_factory: Callable[[], UploadFile],
) -> None:
    class BlockingVision(DeterministicVision):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def analyze(self, **kwargs: object) -> tuple[VisionFacts, str]:
            self.started.set()
            await self.release.wait()
            return await super().analyze(**kwargs)

    vision = BlockingVision()
    orchestrator = AnalysisOrchestrator(vision=vision)  # type: ignore[arg-type]
    owner_stages: list[str] = []
    follower_stages: list[str] = []

    async def owner_progress(stage: str) -> None:
        owner_stages.append(stage)

    async def follower_progress(stage: str) -> None:
        follower_stages.append(stage)

    owner = asyncio.create_task(
        orchestrator.analyze(
            upload=upload_factory(),
            room_hint="toilet",
            progress=owner_progress,
        )
    )
    await vision.started.wait()
    follower = asyncio.create_task(
        orchestrator.analyze(
            upload=upload_factory(),
            room_hint="toilet",
            progress=follower_progress,
        )
    )
    await asyncio.sleep(0)
    vision.release.set()
    await asyncio.gather(owner, follower)

    assert vision.calls == 1
    assert owner_stages == ["intake_complete", "vision_complete"]
    assert follower_stages == ["intake_complete", "vision_complete"]

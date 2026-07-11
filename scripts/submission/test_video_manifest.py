from pathlib import Path

from video_manifest import FINAL_PATH, SEGMENTS, SOURCE_COPY


SOURCE_DURATION = 56.676667


def test_total_segment_duration_is_76_seconds() -> None:
    assert sum(segment["duration"] for segment in SEGMENTS) == 76


def test_demo_segments_stay_within_source_recording() -> None:
    for segment in SEGMENTS:
        if segment["type"] != "demo":
            continue

        assert 0 <= segment["source_start"] < SOURCE_DURATION
        assert (
            segment["source_start"] + segment["source_duration"]
            <= SOURCE_DURATION
        )


def test_every_segment_has_narration_and_caption() -> None:
    for segment in SEGMENTS:
        assert segment["narration_ja"]
        assert segment["caption_ja"]


def test_narration_states_safety_boundaries() -> None:
    narration = "".join(segment["narration_ja"] for segment in SEGMENTS)

    for term in ("医療", "介護", "保険", "施工判断"):
        assert term in narration


def test_media_paths_are_outside_repository() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    assert repo_root not in SOURCE_COPY.parents
    assert repo_root not in FINAL_PATH.parents

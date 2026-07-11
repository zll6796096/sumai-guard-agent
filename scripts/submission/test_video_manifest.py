import hashlib
import re
import subprocess
from pathlib import Path

import pytest
import render_hackathon_video as renderer
import video_manifest as manifest
from video_manifest import BASE, FINAL_PATH, SEGMENTS, SOURCE_COPY, WORK


SOURCE_DURATION = 56.676667
AUDITED_SOURCE_SHA256 = (
    "5771d92ce3e8cdf194afafd2353c2bccee729d78c61888e64c07e6332fb16ed6"
)
PROTECTED_SOURCE_RANGE = (3.3, 6.0)
EXPECTED_IDS = (
    "01_problem",
    "02_agent",
    "03_input",
    "04_analysis",
    "05_visible_risk",
    "06_actions",
    "07_boundary",
    "08_evidence",
)
EXPECTED_TYPES = ("card", "card", "demo", "demo", "demo", "demo", "card", "card")
EXPECTED_DURATIONS = (7, 8, 9, 6, 14, 17, 8, 7)
EXPECTED_COPY = (
    (
        "転倒する前に、親の家を一枚で点検",
        "離れて暮らす家族が、事故の前に安全対話を始めるためのAIエージェント",
        "離れて暮らす親の家。見過ごされる危険。",
        "離れて暮らす親の家。転倒につながる危険は、事故が起きるまで見過ごされがちです。",
    ),
    (
        "一枚の写真から、次の行動まで",
        "見える危険を抽出 → 決定論ルールで判断 → 3段階の行動へ",
        "AI Agent：確認・判断・タスク整理",
        "このAIエージェントは、一枚の写真から見える危険を確認し、次の行動まで整理します。",
    ),
    (
        "質問票なし。写真を一枚。",
        "部屋を選び、カメラまたはライブラリから入力",
        "1 PHOTO IN",
        "質問票は不要です。部屋を選び、写真を一枚撮影、または選択します。",
    ),
    (
        "Cloud Run × Gemini 2.5 Flash",
        "転倒・滑り・つまずきの候補を抽出",
        "REAL GEMINI / STRICT MODE",
        "Cloud Run上で、Gemini 2.5 Flashが、転倒、滑り、つまずきの候補を抽出します。",
    ),
    (
        "見える危険を、見える形に",
        "赤い枠と慎重な根拠説明",
        "VISIBLE EVIDENCE ONLY",
        "危険箇所を赤い枠で可視化。写真で確認できる根拠だけを、慎重に提示します。",
    ),
    (
        "迷わない、3段階の次の行動",
        "今日できること / 福祉用具の相談 / 専門施工",
        "GEMINIは候補抽出。行動区分は決定論ルール。",
        "その後、決定論ルールで、家族が今日できること、福祉用具の相談、専門施工の三段階に分けます。",
    ),
    (
        "安全のための境界",
        "アプリ内に永続保存しない / Gemini送信前にEXIF除去 / 専門家への相談を促す",
        "医療・介護・保険・施工判断を置き換えません",
        "画像はアプリ内に永続保存せず、Geminiへ送る前にEXIF情報を除去。"
        "医療、介護、保険、施工判断の代わりにはなりません。",
    ),
    (
        "つくる。まわす。とどける。",
        "Public GitHub / Cloud Run / Gemini strict mode / 73 tests passed",
        "事故の前に、家族の安全対話を。",
        "公開コードと動作デモはこちら。事故の前に、家族の安全対話を始めます。",
    ),
)
EXPECTED_DEMO_WINDOWS = (
    ("03_input", 0, 3),
    ("04_analysis", 6, 22),
    ("05_visible_risk", 28, 10),
    ("06_actions", 38, 17),
)
EXPECTED_PRIVACY_PILLS = (
    "アプリ内に永続保存しない",
    "送信前にEXIF除去",
    "専門家へ相談",
)
FORBIDDEN_LOCAL_LITERALS = (
    ("macOS private temporary path", b"/private" + b"/var/folders/"),
    ("Photos provider path component", b"NSItem" + b"Provider"),
)
MACOS_USER_PATH = re.compile(
    rb"/Users" + rb"/(?!<)[^/\x00\s]+(?:/|$)"
)
UUID_SHAPE = re.compile(
    rb"(?<![0-9a-fA-F])"
    rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    rb"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    rb"(?![0-9a-fA-F])"
)


def tracked_blob_privacy_markers(content: bytes) -> list[str]:
    markers = [
        label
        for label, literal in FORBIDDEN_LOCAL_LITERALS
        if literal in content
    ]
    if MACOS_USER_PATH.search(content):
        markers.append("macOS user path")
    if UUID_SHAPE.search(content):
        markers.append("UUID-shaped identifier")
    return markers


def test_exact_ordered_segment_contract() -> None:
    ids = tuple(segment["id"] for segment in SEGMENTS)

    assert len(SEGMENTS) == 8
    assert ids == EXPECTED_IDS
    assert len(set(ids)) == len(ids)
    assert tuple(segment["type"] for segment in SEGMENTS) == EXPECTED_TYPES
    assert tuple(segment["duration"] for segment in SEGMENTS) == EXPECTED_DURATIONS
    assert manifest.SOURCE_SHA256 == AUDITED_SOURCE_SHA256


def test_segment_copy_matches_approved_timeline() -> None:
    actual_copy = tuple(
        (
            segment["heading"],
            segment["body"],
            segment["caption_ja"],
            segment["narration_ja"],
        )
        for segment in SEGMENTS
    )

    assert actual_copy == EXPECTED_COPY


def test_segments_have_required_common_and_kind_specific_fields() -> None:
    common_fields = {
        "id",
        "type",
        "duration",
        "heading",
        "body",
        "caption_ja",
        "narration_ja",
    }
    text_fields = common_fields - {"duration"}
    source_fields = {"source_start", "source_duration"}

    for segment in SEGMENTS:
        assert common_fields <= segment.keys()
        assert segment["duration"] > 0
        assert all(segment[field] for field in text_fields)
        if segment["type"] == "demo":
            assert source_fields <= segment.keys()
        else:
            assert source_fields.isdisjoint(segment.keys())


def test_total_segment_duration_is_76_seconds() -> None:
    assert sum(segment["duration"] for segment in SEGMENTS) == 76


def test_demo_segments_stay_within_source_recording() -> None:
    actual_windows = []
    for segment in SEGMENTS:
        if segment["type"] != "demo":
            continue

        actual_windows.append(
            (segment["id"], segment["source_start"], segment["source_duration"])
        )
        assert 0 <= segment["source_start"] < SOURCE_DURATION
        assert (
            segment["source_start"] + segment["source_duration"]
            <= SOURCE_DURATION
        )

    assert tuple(actual_windows) == EXPECTED_DEMO_WINDOWS


def test_demo_segments_exclude_audited_photo_picker_interval() -> None:
    protected_start, protected_end = PROTECTED_SOURCE_RANGE
    demo_segments = {
        segment["id"]: segment
        for segment in SEGMENTS
        if segment["type"] == "demo"
    }

    for segment in demo_segments.values():
        source_start = segment["source_start"]
        source_end = source_start + segment["source_duration"]
        assert source_end <= protected_start or source_start >= protected_end

    input_end = (
        demo_segments["03_input"]["source_start"]
        + demo_segments["03_input"]["source_duration"]
    )
    assert input_end <= protected_start
    assert demo_segments["04_analysis"]["source_start"] >= protected_end


def test_narration_states_safety_boundaries() -> None:
    narration = "".join(segment["narration_ja"] for segment in SEGMENTS)

    for term in ("医療", "介護", "保険", "施工判断"):
        assert term in narration


def test_boundary_segment_uses_exact_approved_negative_disclaimer() -> None:
    boundary = next(segment for segment in SEGMENTS if segment["id"] == "07_boundary")

    assert boundary["narration_ja"] == (
        "画像はアプリ内に永続保存せず、Geminiへ送る前にEXIF情報を除去。"
        "医療、介護、保険、施工判断の代わりにはなりません。"
    )
    assert "代わりにはなりません" in boundary["narration_ja"]


def test_boundary_frame_uses_exact_privacy_pills() -> None:
    assert renderer.PRIVACY_PILLS == EXPECTED_PRIVACY_PILLS
    assert renderer.EVIDENCE_TEST_PILL == "73 tests PASS"


def test_media_paths_are_outside_repository(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2].resolve()

    for media_path in (BASE, SOURCE_COPY, WORK, FINAL_PATH):
        resolved_path = media_path.resolve(strict=False)
        assert not resolved_path.is_relative_to(repo_root)

    sample = tmp_path / "source.mp4"
    sample.write_bytes(b"audited source")
    expected = hashlib.sha256(b"audited source").hexdigest()
    assert renderer.sha256_file(sample) == expected

    with pytest.raises(SystemExit) as exc_info:
        renderer.validate_source_identity(sample)

    message = str(exc_info.value)
    assert message == (
        "source SHA-256 mismatch: expected 5771d92ce3e8, "
        f"actual {expected[:12]}"
    )
    assert str(sample) not in message


def test_tracked_files_do_not_publish_local_private_paths() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    tracked_output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout
    tracked_files = [
        repo_root / path.decode()
        for path in tracked_output.split(b"\0")
        if path
    ]
    violations = {
        str(path.relative_to(repo_root)): tracked_blob_privacy_markers(
            path.read_bytes()
        )
        for path in tracked_files
    }
    violations = {path: matches for path, matches in violations.items() if matches}

    assert violations == {}


def test_uuid_shape_detector_does_not_need_a_real_identifier() -> None:
    synthetic_uuid = b"123e4567" + b"-e89b-12d3-a456-426614174000"

    assert tracked_blob_privacy_markers(synthetic_uuid) == [
        "UUID-shaped identifier"
    ]

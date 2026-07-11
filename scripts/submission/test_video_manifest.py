from pathlib import Path

from video_manifest import BASE, FINAL_PATH, SEGMENTS, SOURCE_COPY, WORK


SOURCE_DURATION = 56.676667
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
        "画像保存なし / EXIF除去 / 専門家への相談を促す",
        "医療・介護・保険・施工判断を置き換えません",
        "画像は保存せず、位置情報を除去。医療、介護、保険、施工判断の代わりにはなりません。",
    ),
    (
        "つくる。まわす。とどける。",
        "Public GitHub / Cloud Run / Gemini strict mode / 34 tests passed",
        "事故の前に、家族の安全対話を。",
        "公開コードと動作デモはこちら。事故の前に、家族の安全対話を始めます。",
    ),
)
EXPECTED_DEMO_WINDOWS = (
    ("03_input", 0, 4),
    ("04_analysis", 4, 24),
    ("05_visible_risk", 28, 10),
    ("06_actions", 38, 17),
)


def test_exact_ordered_segment_contract() -> None:
    ids = tuple(segment["id"] for segment in SEGMENTS)

    assert len(SEGMENTS) == 8
    assert ids == EXPECTED_IDS
    assert len(set(ids)) == len(ids)
    assert tuple(segment["type"] for segment in SEGMENTS) == EXPECTED_TYPES
    assert tuple(segment["duration"] for segment in SEGMENTS) == EXPECTED_DURATIONS


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


def test_narration_states_safety_boundaries() -> None:
    narration = "".join(segment["narration_ja"] for segment in SEGMENTS)

    for term in ("医療", "介護", "保険", "施工判断"):
        assert term in narration


def test_boundary_segment_uses_exact_approved_negative_disclaimer() -> None:
    boundary = next(segment for segment in SEGMENTS if segment["id"] == "07_boundary")

    assert boundary["narration_ja"] == (
        "画像は保存せず、位置情報を除去。"
        "医療、介護、保険、施工判断の代わりにはなりません。"
    )
    assert "代わりにはなりません" in boundary["narration_ja"]


def test_media_paths_are_outside_repository() -> None:
    repo_root = Path(__file__).resolve().parents[2].resolve()

    for media_path in (BASE, SOURCE_COPY, WORK, FINAL_PATH):
        resolved_path = media_path.resolve(strict=False)
        assert not resolved_path.is_relative_to(repo_root)

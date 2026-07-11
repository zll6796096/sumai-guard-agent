# SumaiGuard Hackathon Submission Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Generate and verify a 70–80 second Japanese YouTube-ready SumaiGuard hackathon demo from the user's real iPhone recording.

**Architecture:** Keep product code untouched. Store a small reproducible media manifest and renderer under scripts/submission, render all large intermediates and the MP4 under the user's Movies folder, and use ffmpeg/ffprobe plus the live smoke test as acceptance evidence.

**Tech Stack:** Python 3.13, Pillow, macOS say with the Kyoko Japanese voice, ffmpeg/ffprobe, pytest, Cloud Run, Gemini 2.5 Flash.

---

## File map

- Create: scripts/submission/video_manifest.py — approved timeline, source spans, narration, visible claims, and stable output paths.
- Create: scripts/submission/test_video_manifest.py — duration, source-span, scope-boundary, and output-path tests.
- Create: scripts/submission/render_hackathon_video.py — title/panel rendering, Kyoko narration synthesis, ffmpeg segment composition, and final concatenation.
- Create: scripts/submission/verify_hackathon_video.py — ffprobe assertions, loudness check, contact-sheet generation, and secret-text guard.
- Create outside Git: /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/source/screen-recording.mp4 — stable copy of the temporary Photos source.
- Create outside Git: /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/work/ — generated cards, narration, segments, and contact sheet.
- Create outside Git: /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/sumai-guard-hackathon-demo-2026.mp4 — final upload artifact.

### Task 1: Lock the approved timeline as tested data

**Files:**
- Create: scripts/submission/test_video_manifest.py
- Create: scripts/submission/video_manifest.py

- [ ] **Step 1: Write the failing manifest tests**

Create scripts/submission/test_video_manifest.py with:

~~~python
from pathlib import Path

from video_manifest import FINAL_PATH, SEGMENTS, SOURCE_COPY


def test_total_duration_is_submission_target() -> None:
    assert sum(segment["duration"] for segment in SEGMENTS) == 76


def test_source_spans_fit_the_real_recording() -> None:
    for segment in SEGMENTS:
        if segment["kind"] == "demo":
            assert 0 <= segment["source_start"] < 56.676667
            assert segment["source_start"] + segment["source_duration"] <= 56.676667


def test_every_segment_has_japanese_narration_and_caption() -> None:
    for segment in SEGMENTS:
        assert segment["narration_ja"].strip()
        assert segment["caption_ja"].strip()


def test_safety_boundary_is_explicit() -> None:
    text = " ".join(segment["narration_ja"] for segment in SEGMENTS)
    for term in ("医療", "介護", "保険", "施工判断"):
        assert term in text


def test_media_outputs_are_outside_git() -> None:
    repo = Path(__file__).resolve().parents[2]
    assert repo not in SOURCE_COPY.parents
    assert repo not in FINAL_PATH.parents
~~~

- [ ] **Step 2: Run the tests and verify the expected red state**

Run:

~~~bash
python3 -m pytest scripts/submission/test_video_manifest.py -v
~~~

Expected: collection fails with ModuleNotFoundError: No module named 'video_manifest'.

- [ ] **Step 3: Implement the exact approved manifest**

Create scripts/submission/video_manifest.py with:

~~~python
from pathlib import Path

BASE = Path.home() / "Movies" / "SumaiGuard-Hackathon-2026"
SOURCE_COPY = BASE / "source" / "screen-recording.mp4"
WORK = BASE / "work"
FINAL_PATH = BASE / "sumai-guard-hackathon-demo-2026.mp4"

SEGMENTS = [
    {
        "id": "01_problem",
        "kind": "card",
        "duration": 7,
        "heading": "転倒する前に、親の家を一枚で点検",
        "body": "離れて暮らす家族が、事故の前に安全対話を始めるためのAIエージェント",
        "caption_ja": "離れて暮らす親の家。見過ごされる危険。",
        "narration_ja": "離れて暮らす親の家。転倒につながる危険は、事故が起きるまで見過ごされがちです。",
    },
    {
        "id": "02_agent",
        "kind": "card",
        "duration": 8,
        "heading": "一枚の写真から、次の行動まで",
        "body": "見える危険を抽出 → 決定論ルールで判断 → 3段階の行動へ",
        "caption_ja": "AI Agent：確認・判断・タスク整理",
        "narration_ja": "このAIエージェントは、一枚の写真から見える危険を確認し、次の行動まで整理します。",
    },
    {
        "id": "03_input",
        "kind": "demo",
        "duration": 9,
        "source_start": 0,
        "source_duration": 4,
        "heading": "質問票なし。写真を一枚。",
        "body": "部屋を選び、カメラまたはライブラリから入力",
        "caption_ja": "1 PHOTO IN",
        "narration_ja": "質問票は不要です。部屋を選び、写真を一枚撮影、または選択します。",
    },
    {
        "id": "04_analysis",
        "kind": "demo",
        "duration": 6,
        "source_start": 4,
        "source_duration": 24,
        "heading": "Cloud Run × Gemini 2.5 Flash",
        "body": "転倒・滑り・つまずきの候補を抽出",
        "caption_ja": "REAL GEMINI / STRICT MODE",
        "narration_ja": "Cloud Run上で、Gemini 2.5 Flashが、転倒、滑り、つまずきの候補を抽出します。",
    },
    {
        "id": "05_visible_risk",
        "kind": "demo",
        "duration": 14,
        "source_start": 28,
        "source_duration": 10,
        "heading": "見える危険を、見える形に",
        "body": "赤い枠と慎重な根拠説明",
        "caption_ja": "VISIBLE EVIDENCE ONLY",
        "narration_ja": "危険箇所を赤い枠で可視化。写真で確認できる根拠だけを、慎重に提示します。",
    },
    {
        "id": "06_actions",
        "kind": "demo",
        "duration": 17,
        "source_start": 38,
        "source_duration": 17,
        "heading": "迷わない、3段階の次の行動",
        "body": "今日できること / 福祉用具の相談 / 専門施工",
        "caption_ja": "GEMINIは候補抽出。行動区分は決定論ルール。",
        "narration_ja": "その後、決定論ルールで、家族が今日できること、福祉用具の相談、専門施工の三段階に分けます。",
    },
    {
        "id": "07_boundary",
        "kind": "card",
        "duration": 8,
        "heading": "安全のための境界",
        "body": "画像保存なし / EXIF除去 / 専門家への相談を促す",
        "caption_ja": "医療・介護・保険・施工判断を置き換えません",
        "narration_ja": "画像は保存せず、位置情報を除去。医療、介護、保険、施工判断の代わりにはなりません。",
    },
    {
        "id": "08_evidence",
        "kind": "card",
        "duration": 7,
        "heading": "つくる。まわす。とどける。",
        "body": "Public GitHub / Cloud Run / Gemini strict mode / 34 tests passed",
        "caption_ja": "事故の前に、家族の安全対話を。",
        "narration_ja": "公開コードと動作デモはこちら。事故の前に、家族の安全対話を始めます。",
    },
]
~~~

- [ ] **Step 4: Run the manifest tests**

Run:

~~~bash
PYTHONPATH=scripts/submission python3 -m pytest scripts/submission/test_video_manifest.py -v
~~~

Expected: 5 passed.

- [ ] **Step 5: Commit the tested manifest**

~~~bash
git add -- scripts/submission/video_manifest.py scripts/submission/test_video_manifest.py
git commit -m "test: lock hackathon video timeline"
~~~

### Task 2: Build the reproducible renderer

**Files:**
- Create: scripts/submission/render_hackathon_video.py

- [ ] **Step 1: Copy the source to a stable path and prove the copy is identical**

Run:

~~~bash
mkdir -p /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/source
cp "/private/var/folders/3n/xskbt7rx7g1846vkrw7tvl4w0000gn/T/TemporaryItems/com.apple.Photos.NSItemProvider/uuid=BDD7B771-5249-4024-8273-0FBC79AD93B6&code=001&library=1&type=3&mode=1&loc=true&cap=true.mp4/ScreenRecording_07-11-2026 23-08-22_1.mp4" \
  /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/source/screen-recording.mp4
shasum -a 256 \
  "/private/var/folders/3n/xskbt7rx7g1846vkrw7tvl4w0000gn/T/TemporaryItems/com.apple.Photos.NSItemProvider/uuid=BDD7B771-5249-4024-8273-0FBC79AD93B6&code=001&library=1&type=3&mode=1&loc=true&cap=true.mp4/ScreenRecording_07-11-2026 23-08-22_1.mp4" \
  /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/source/screen-recording.mp4
~~~

Expected: both SHA-256 values are identical.

- [ ] **Step 2: Implement the renderer with narrow responsibilities**

Create scripts/submission/render_hackathon_video.py with:

~~~python
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from video_manifest import FINAL_PATH, SEGMENTS, SOURCE_COPY, WORK

W, H = 1920, 1080
BOLD_PATH = Path("/System/Library/AssetsV2/PreinstalledAssetsV2/InstallWithOs/com_apple_MobileAsset_Font7/0703ece025f7511095fc290b30bc2d3d28d509a9.asset/AssetData/YuGothic-Bold.otf")
MEDIUM_PATH = Path("/System/Library/AssetsV2/PreinstalledAssetsV2/InstallWithOs/com_apple_MobileAsset_Font7/11ead4dd9f3a3503b4ced2546782dd8bc31871c9.asset/AssetData/YuGothic-Medium.otf")
BG = "#0F1020"
PANEL = "#17213B"
WHITE = "#F7F8FA"
MUTED = "#B8C2DC"
BLUE = "#4C7DFF"
VIOLET = "#6C5CE7"


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD_PATH if bold else MEDIUM_PATH), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and draw.textbbox((0, 0), candidate, font=face)[2] > width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def draw_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    face: ImageFont.FreeTypeFont,
    fill: str,
    width: int,
    gap: int = 12,
) -> int:
    x, y = xy
    for line in wrap(draw, text, face, width):
        draw.text((x, y), line, font=face, fill=fill)
        box = draw.textbbox((x, y), line, font=face)
        y += box[3] - box[1] + gap
    return y


def pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    x, y = xy
    face = font(25, True)
    box = draw.textbbox((0, 0), text, font=face)
    draw.rounded_rectangle((x, y, x + box[2] + 34, y + 50), 25, fill=BLUE)
    draw.text((x + 17, y + 8), text, font=face, fill=WHITE)


def render_frame(segment: dict[str, object], output: Path) -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    heading = str(segment["heading"])
    body = str(segment["body"])
    caption = str(segment["caption_ja"])

    if segment["kind"] == "card":
        draw.rounded_rectangle((135, 120, 1785, 870), 38, fill=PANEL)
        draw.text((190, 175), "親の家 安全チェックAI", font=font(30, True), fill=BLUE)
        y = draw_lines(draw, heading, (190, 270), font(65, True), WHITE, 1460, 18)
        draw_lines(draw, body, (190, y + 38), font(35), MUTED, 1450, 15)
        if segment["id"] == "02_agent":
            labels = ["見える危険を抽出", "決定論ルール", "3段階の行動"]
            for index, label in enumerate(labels):
                x = 190 + index * 510
                draw.rounded_rectangle((x, 640, x + 410, 760), 24, fill="#243355")
                draw.text((x + 28, 678), label, font=font(28, True), fill=WHITE)
                if index < 2:
                    draw.text((x + 435, 675), "→", font=font(42, True), fill=VIOLET)
        elif segment["id"] == "07_boundary":
            pill(draw, (190, 665), "画像保存なし")
            pill(draw, (500, 665), "EXIF除去")
            pill(draw, (750, 665), "専門家へ相談")
        elif segment["id"] == "08_evidence":
            pill(draw, (190, 665), "Public GitHub")
            pill(draw, (500, 665), "Cloud Run")
            pill(draw, (750, 665), "Gemini strict")
            pill(draw, (1070, 665), "34 tests PASS")
    else:
        draw.rounded_rectangle((75, 55, 605, 1005), 42, fill="#070A16")
        draw.rounded_rectangle((690, 110, 1810, 850), 34, fill=PANEL)
        draw.text((750, 175), "実機デモ", font=font(28, True), fill=BLUE)
        y = draw_lines(draw, heading, (750, 260), font(54, True), WHITE, 960, 18)
        draw_lines(draw, body, (750, y + 38), font(34), MUTED, 930, 16)
        if segment["id"] == "04_analysis":
            pill(draw, (750, 650), "Cloud Run")
            pill(draw, (1010, 650), "Gemini 2.5 Flash")
            pill(draw, (1390, 650), "Strict mode")

    draw.rectangle((0, 900, W, H), fill="#090C18")
    draw.text((90, 930), caption, font=font(39, True), fill=WHITE)
    draw.text((90, 1003), "SUMAIGUARD AGENT", font=font(20, True), fill=VIOLET)
    image.save(output, quality=95)


def synthesize_audio(segment: dict[str, object], output: Path) -> None:
    raw = output.with_suffix(".aiff")
    run(["say", "-v", "Kyoko", "-r", "178", "-o", str(raw), str(segment["narration_ja"])])
    target = float(segment["duration"])
    raw_duration = probe_duration(raw)
    filters: list[str] = []
    if raw_duration > target - 0.35:
        filters.append(f"atempo={raw_duration / (target - 0.35):.6f}")
    filters.extend([
        "loudnorm=I=-16:TP=-1.5:LRA=7",
        f"apad=pad_dur={target}",
        f"atrim=0:{target}",
    ])
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(raw), "-af", ",".join(filters),
        "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
        str(output),
    ])


def video_encode_args() -> list[str]:
    return [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-map_metadata", "-1",
    ]


def render_segment(segment: dict[str, object], frame: Path, audio: Path, output: Path) -> None:
    duration = float(segment["duration"])
    if segment["kind"] == "card":
        args = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-framerate", "30", "-t", str(duration), "-i", str(frame),
            "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-t", str(duration),
            *video_encode_args(), str(output),
        ]
    else:
        start = float(segment["source_start"])
        source_duration = float(segment["source_duration"])
        speed = duration / source_duration
        graph = (
            f"[0:v]setpts={speed:.8f}*PTS,scale=-2:920:flags=lanczos[phone];"
            "[1:v][phone]overlay=120:(H-h)/2:shortest=1[outv]"
        )
        args = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(start), "-t", str(source_duration), "-i", str(SOURCE_COPY),
            "-loop", "1", "-framerate", "30", "-t", str(duration), "-i", str(frame),
            "-i", str(audio), "-filter_complex", graph,
            "-map", "[outv]", "-map", "2:a:0", "-t", str(duration),
            *video_encode_args(), str(output),
        ]
    run(args)


def main() -> None:
    if not SOURCE_COPY.exists():
        raise SystemExit(f"missing source: {SOURCE_COPY}")
    if probe_duration(SOURCE_COPY) < 56.6:
        raise SystemExit("source recording is unexpectedly short")
    if not BOLD_PATH.exists() or not MEDIUM_PATH.exists():
        raise SystemExit("approved Japanese fonts are unavailable")

    WORK.mkdir(parents=True, exist_ok=True)
    FINAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []
    for segment in SEGMENTS:
        segment_id = str(segment["id"])
        frame = WORK / f"{segment_id}.png"
        audio = WORK / f"{segment_id}.m4a"
        video = WORK / f"{segment_id}.mp4"
        render_frame(segment, frame)
        synthesize_audio(segment, audio)
        render_segment(segment, frame, audio, video)
        segments.append(video)

    concat = WORK / "concat.txt"
    concat.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in segments),
        encoding="utf-8",
    )
    temporary = FINAL_PATH.with_name(FINAL_PATH.stem + "-rendering.mp4")
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-c", "copy", "-movflags", "+faststart", str(temporary),
    ])
    shutil.move(temporary, FINAL_PATH)
    print(f"rendered: {FINAL_PATH}")


if __name__ == "__main__":
    main()
~~~

- [ ] **Step 3: Run the renderer**

Run:

~~~bash
PYTHONPATH=scripts/submission python3 scripts/submission/render_hackathon_video.py
~~~

Expected final line:

~~~text
rendered: /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/sumai-guard-hackathon-demo-2026.mp4
~~~

- [ ] **Step 4: Commit the renderer**

~~~bash
git add -- scripts/submission/render_hackathon_video.py
git commit -m "feat: add reproducible hackathon video renderer"
~~~

### Task 3: Add machine-verifiable media acceptance checks

**Files:**
- Create: scripts/submission/verify_hackathon_video.py

- [ ] **Step 1: Implement exact verification assertions**

Create scripts/submission/verify_hackathon_video.py with:

~~~python
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from video_manifest import FINAL_PATH, WORK

RENDERER = Path(__file__).with_name("render_hackathon_video.py")
PROHIBITED = ("GEMINI_API_KEY", "zll6796096@gmail.com", "key.json")


def capture(args: list[str]) -> str:
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def main() -> None:
    if not FINAL_PATH.exists():
        raise SystemExit(f"missing final video: {FINAL_PATH}")

    probe_text = capture([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:format_tags:stream=codec_name,codec_type,width,height",
        "-of", "json", str(FINAL_PATH),
    ])
    probe = json.loads(probe_text)
    duration = float(probe["format"]["duration"])
    assert 70 <= duration <= 80, duration
    print(f"PASS duration {duration:.3f}s")

    videos = [s for s in probe["streams"] if s["codec_type"] == "video"]
    audios = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    assert len(videos) == 1
    assert videos[0]["codec_name"] == "h264"
    assert (videos[0]["width"], videos[0]["height"]) == (1920, 1080)
    print("PASS video h264 1920x1080")
    assert len(audios) == 1 and audios[0]["codec_name"] == "aac"
    print("PASS audio aac")

    volume = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(FINAL_PATH),
            "-af", "volumedetect", "-f", "null", "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    mean_match = re.search(r"mean_volume: (-?\d+(?:\.\d+)?) dB", volume)
    max_match = re.search(r"max_volume: (-?\d+(?:\.\d+)?) dB", volume)
    assert mean_match and max_match
    mean_db = float(mean_match.group(1))
    max_db = float(max_match.group(1))
    assert -24 <= mean_db <= -12, mean_db
    assert max_db <= -1, max_db
    print(f"PASS loudness mean={mean_db:.1f}dB max={max_db:.1f}dB")

    scan_text = RENDERER.read_text(encoding="utf-8") + probe_text
    for term in PROHIBITED:
        assert term not in scan_text, term
    print("PASS prohibited-text scan")

    WORK.mkdir(parents=True, exist_ok=True)
    contact = WORK / "contact-sheet.jpg"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(FINAL_PATH),
            "-vf", "fps=1/5,scale=480:-2,tile=4x4:padding=8:margin=8:color=white",
            "-frames:v", "1", str(contact),
        ],
        check=True,
    )
    for second, name in ((0, "review-00.jpg"), (38, "review-38.jpg"), (75, "review-75.jpg")):
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", str(second), "-i", str(FINAL_PATH),
                "-frames:v", "1", "-q:v", "2", str(WORK / name),
            ],
            check=True,
        )
    print(f"contact sheet: {contact}")


if __name__ == "__main__":
    main()
~~~

- [ ] **Step 2: Run verification**

Run:

~~~bash
PYTHONPATH=scripts/submission python3 scripts/submission/verify_hackathon_video.py
~~~

Expected:

~~~text
PASS duration
PASS video h264 1920x1080
PASS audio aac
PASS loudness
PASS prohibited-text scan
contact sheet: /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/work/contact-sheet.jpg
~~~

- [ ] **Step 3: Visually inspect the contact sheet and three review frames**

Open the four generated JPG files with the local image viewer. Reject the render if Japanese glyphs are missing, phone text is cropped, captions collide, secrets appear, or the first/last frames do not communicate the problem and evidence.

- [ ] **Step 4: Commit the verifier**

~~~bash
git add -- scripts/submission/verify_hackathon_video.py
git commit -m "test: verify hackathon video artifact"
~~~

### Task 4: Re-run project and live-service gates

**Files:**
- No file changes.

- [ ] **Step 1: Run the complete local suite**

~~~bash
./scripts/test_all.sh
~~~

Expected: 34 backend tests pass, frontend import passes, and Docker Compose config passes.

- [ ] **Step 2: Prove real Gemini participation on Cloud Run**

~~~bash
SUMAI_AGENT_URL=https://sumai-agent-sxielk4wua-an.a.run.app \
  python3 scripts/smoke_real_gemini.py
~~~

Expected: home and non-home analyses both pass and the status reports mock_mode false, require_real_gemini true, and gemini-2.5-flash.

- [ ] **Step 3: Verify public repository and deployed frontend**

~~~bash
gh repo view zll6796096/sumai-guard-agent --json url,visibility,defaultBranchRef
curl -fsS --max-time 20 https://sumai-web-sxielk4wua-an.a.run.app \
  | rg "親の家 安全チェックAI"
~~~

Expected: repository visibility PUBLIC, default branch main, and deployed page title match.

- [ ] **Step 4: Review Git state**

~~~bash
git diff --check
git status --short
git log -5 --oneline
~~~

Expected: no unstaged or untracked files; only the intentional submission-tool commits are new.

### Task 5: Prepare upload handoff without publishing

**Files:**
- No repository changes.

- [ ] **Step 1: Record the exact upload artifact metadata**

~~~bash
shasum -a 256 /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/sumai-guard-hackathon-demo-2026.mp4
ls -lh /Users/zhanglonglong/Movies/SumaiGuard-Hackathon-2026/sumai-guard-hackathon-demo-2026.mp4
~~~

- [ ] **Step 2: Prepare the YouTube draft**

Use:

- Title: 親の家 安全チェックAI｜1枚の写真から転倒リスクと次の行動を整理
- Visibility: unlisted
- Category: Science & Technology
- Audience: not made for kids
- Description claims must match the fresh Task 4 evidence.

- [ ] **Step 3: Stop before external upload**

Uploading the MP4 and saving YouTube metadata are representational external actions. Present the final MP4 path, SHA-256, duration, contact sheet, proposed title/description, and fresh service evidence to the user, then request action-time confirmation.

### Plan self-review

- Spec coverage: all eleven design sections map to Tasks 1–5.
- Scope: product code and deployment remain untouched; only submission tooling and external media are created.
- Type consistency: SEGMENTS, SOURCE_COPY, WORK, and FINAL_PATH are defined once in video_manifest.py and imported by both renderer and verifier.
- Completeness scan: every code-producing step contains the exact file content or an exact command.
- Risk controls: stable source copy, real-Gemini recheck, secret scan, professional-boundary narration, and external-action confirmation are explicit.

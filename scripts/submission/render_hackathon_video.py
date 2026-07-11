from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from video_manifest import FINAL_PATH, SEGMENTS, SOURCE_COPY, SOURCE_SHA256, WORK


W, H = 1920, 1080
BOLD_PATH = Path(
    "/System/Library/AssetsV2/PreinstalledAssetsV2/InstallWithOs/"
    "com_apple_MobileAsset_Font7/"
    "0703ece025f7511095fc290b30bc2d3d28d509a9.asset/"
    "AssetData/YuGothic-Bold.otf"
)
MEDIUM_PATH = Path(
    "/System/Library/AssetsV2/PreinstalledAssetsV2/InstallWithOs/"
    "com_apple_MobileAsset_Font7/"
    "11ead4dd9f3a3503b4ced2546782dd8bc31871c9.asset/"
    "AssetData/YuGothic-Medium.otf"
)
BG = "#0F1020"
PANEL = "#17213B"
WHITE = "#F7F8FA"
MUTED = "#B8C2DC"
BLUE = "#4C7DFF"
VIOLET = "#6C5CE7"
BT709_LIMITED_FILTER = (
    "format=yuv420p,"
    "setparams=range=tv:color_primaries=bt709:"
    "color_trc=bt709:colorspace=bt709"
)
VIDEO_SIGNATURE_FIELDS = (
    "codec_name",
    "profile",
    "level",
    "width",
    "height",
    "pix_fmt",
    "color_range",
    "color_space",
    "color_transfer",
    "color_primaries",
    "r_frame_rate",
    "time_base",
    "extradata_size",
)
AUDIO_SIGNATURE_FIELDS = (
    "codec_name",
    "profile",
    "sample_rate",
    "channels",
    "channel_layout",
    "time_base",
    "extradata_size",
)
PRIVACY_PILLS = (
    "アプリ内に永続保存しない",
    "送信前にEXIF除去",
    "専門家へ相談",
)
EVIDENCE_TEST_PILL = "73 tests PASS"


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source_identity(path: Path = SOURCE_COPY) -> None:
    actual = sha256_file(path)
    if actual != SOURCE_SHA256:
        raise SystemExit(
            "source SHA-256 mismatch: "
            f"expected {SOURCE_SHA256[:12]}, actual {actual[:12]}"
        )


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def probe_stream_signature(path: Path) -> dict[str, dict[str, object]]:
    fields = ("codec_type", *VIDEO_SIGNATURE_FIELDS, *AUDIO_SIGNATURE_FIELDS)
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            f"stream={','.join(fields)}",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    streams = {
        str(stream["codec_type"]): stream
        for stream in json.loads(result.stdout)["streams"]
    }
    if "video" not in streams or "audio" not in streams:
        raise SystemExit(f"segment is missing video or audio: {path}")
    return {
        "video": {
            field: streams["video"].get(field)
            for field in VIDEO_SIGNATURE_FIELDS
        },
        "audio": {
            field: streams["audio"].get(field)
            for field in AUDIO_SIGNATURE_FIELDS
        },
    }


def ensure_compatible_segments(paths: list[Path]) -> None:
    if not paths:
        raise SystemExit("no rendered segments to concatenate")
    expected = probe_stream_signature(paths[0])
    required_video_metadata = {
        "pix_fmt": "yuv420p",
        "color_range": "tv",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }
    actual_video_metadata = {
        field: expected["video"][field]
        for field in required_video_metadata
    }
    if actual_video_metadata != required_video_metadata:
        raise SystemExit(
            "rendered segments do not use limited-range BT.709 yuv420p: "
            f"{json.dumps(actual_video_metadata, sort_keys=True)}"
        )
    for path in paths[1:]:
        actual = probe_stream_signature(path)
        if actual != expected:
            raise SystemExit(
                f"incompatible segment streams: {path}\n"
                f"expected: {json.dumps(expected, sort_keys=True)}\n"
                f"actual: {json.dumps(actual, sort_keys=True)}"
            )


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = BOLD_PATH if bold else MEDIUM_PATH
    return ImageFont.truetype(str(path), size)


def wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    face: ImageFont.FreeTypeFont,
    width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        box = draw.textbbox((0, 0), candidate, font=face)
        if current and box[2] - box[0] > width:
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
    pill_width = box[2] - box[0] + 34
    draw.rounded_rectangle((x, y, x + pill_width, y + 50), 25, fill=BLUE)
    draw.text((x + 17, y + 8), text, font=face, fill=WHITE)


def render_frame(segment: dict[str, object], output: Path) -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    heading = str(segment["heading"])
    body = str(segment["body"])
    caption = str(segment["caption_ja"])

    if segment["type"] == "card":
        draw.rounded_rectangle((135, 120, 1785, 870), 38, fill=PANEL)
        draw.text(
            (190, 175),
            "親の家 安全チェックAI",
            font=font(30, True),
            fill=BLUE,
        )
        y = draw_lines(
            draw,
            heading,
            (190, 270),
            font(65, True),
            WHITE,
            1460,
            18,
        )
        draw_lines(draw, body, (190, y + 38), font(35), MUTED, 1450, 15)
        if segment["id"] == "02_agent":
            labels = ["見える危険を抽出", "決定論ルール", "3段階の行動"]
            for index, label in enumerate(labels):
                x = 190 + index * 510
                draw.rounded_rectangle(
                    (x, 640, x + 410, 760),
                    24,
                    fill="#243355",
                )
                draw.text(
                    (x + 28, 678),
                    label,
                    font=font(28, True),
                    fill=WHITE,
                )
                if index < 2:
                    draw.text(
                        (x + 435, 675),
                        "→",
                        font=font(42, True),
                        fill=VIOLET,
                    )
        elif segment["id"] == "07_boundary":
            for x, label in zip((190, 650, 1030), PRIVACY_PILLS, strict=True):
                pill(draw, (x, 665), label)
        elif segment["id"] == "08_evidence":
            pill(draw, (190, 665), "Public GitHub")
            pill(draw, (500, 665), "Cloud Run")
            pill(draw, (750, 665), "Gemini strict")
            pill(draw, (1070, 665), EVIDENCE_TEST_PILL)
    else:
        draw.rounded_rectangle((75, 55, 605, 1005), 42, fill="#070A16")
        draw.rounded_rectangle((690, 110, 1810, 850), 34, fill=PANEL)
        draw.text((750, 175), "実機デモ", font=font(28, True), fill=BLUE)
        y = draw_lines(
            draw,
            heading,
            (750, 260),
            font(54, True),
            WHITE,
            960,
            18,
        )
        draw_lines(draw, body, (750, y + 38), font(34), MUTED, 930, 16)
        if segment["id"] == "04_analysis":
            pill(draw, (750, 650), "Cloud Run")
            pill(draw, (1010, 650), "Gemini 2.5 Flash")
            pill(draw, (1390, 650), "Strict mode")

    draw.rectangle((0, 900, W, H), fill="#090C18")
    caption_x = 90 if segment["type"] == "card" else 750
    draw.text((caption_x, 930), caption, font=font(39, True), fill=WHITE)
    draw.text(
        (caption_x, 1003),
        "SUMAIGUARD AGENT",
        font=font(20, True),
        fill=VIOLET,
    )
    image.save(output)


def synthesize_audio(segment: dict[str, object], output: Path) -> None:
    raw = output.with_suffix(".aiff")
    run(
        [
            "say",
            "-v",
            "Kyoko",
            "-r",
            "178",
            "-o",
            str(raw),
            str(segment["narration_ja"]),
        ]
    )
    target = float(segment["duration"])
    raw_duration = probe_duration(raw)
    filters: list[str] = []
    if raw_duration > target - 0.35:
        filters.append(f"atempo={raw_duration / (target - 0.35):.6f}")
    filters.extend(
        [
            "loudnorm=I=-16:TP=-1.5:LRA=7",
            f"apad=pad_dur={target}",
            f"atrim=0:{target}",
        ]
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(raw),
            "-af",
            ",".join(filters),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output),
        ]
    )


def video_encode_args() -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-color_range",
        "tv",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-r",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-map_metadata",
        "-1",
    ]


def render_segment(
    segment: dict[str, object],
    frame: Path,
    audio: Path,
    output: Path,
) -> None:
    duration = float(segment["duration"])
    if segment["type"] == "card":
        args = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-t",
            str(duration),
            "-i",
            str(frame),
            "-i",
            str(audio),
            "-vf",
            BT709_LIMITED_FILTER,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            str(duration),
            *video_encode_args(),
            str(output),
        ]
    else:
        start = float(segment["source_start"])
        source_duration = float(segment["source_duration"])
        speed = duration / source_duration
        graph = (
            f"[0:v]setpts={speed:.8f}*PTS,"
            "scale=-2:920:flags=lanczos:in_range=pc:out_range=tv,"
            f"{BT709_LIMITED_FILTER}[phone];"
            "[1:v][phone]overlay=120:(H-h)/2:shortest=1,"
            f"{BT709_LIMITED_FILTER}[outv]"
        )
        args = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(start),
            "-t",
            str(source_duration),
            "-i",
            str(SOURCE_COPY),
            "-loop",
            "1",
            "-framerate",
            "30",
            "-t",
            str(duration),
            "-i",
            str(frame),
            "-i",
            str(audio),
            "-filter_complex",
            graph,
            "-map",
            "[outv]",
            "-map",
            "2:a:0",
            "-t",
            str(duration),
            *video_encode_args(),
            str(output),
        ]
    run(args)


def main() -> None:
    if not SOURCE_COPY.exists():
        raise SystemExit(f"missing source: {SOURCE_COPY}")
    validate_source_identity()
    if probe_duration(SOURCE_COPY) < 56.6:
        raise SystemExit("source recording is unexpectedly short")
    if not BOLD_PATH.exists() or not MEDIUM_PATH.exists():
        raise SystemExit("approved Japanese fonts are unavailable")

    WORK.mkdir(parents=True, exist_ok=True)
    FINAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    for segment in SEGMENTS:
        segment_id = str(segment["id"])
        frame = WORK / f"{segment_id}.png"
        audio = WORK / f"{segment_id}.m4a"
        video = WORK / f"{segment_id}.mp4"
        render_frame(segment, frame)
        synthesize_audio(segment, audio)
        render_segment(segment, frame, audio, video)
        segment_paths.append(video)

    ensure_compatible_segments(segment_paths)
    concat = WORK / "concat.txt"
    concat.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in segment_paths),
        encoding="utf-8",
    )
    temporary = FINAL_PATH.with_name(f"{FINAL_PATH.stem}-rendering.mp4")
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
    )
    shutil.move(temporary, FINAL_PATH)
    print(f"rendered: {FINAL_PATH}")


if __name__ == "__main__":
    main()

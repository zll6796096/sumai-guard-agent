from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from video_manifest import FINAL_PATH, WORK


RENDERER = Path(__file__).with_name("render_hackathon_video.py")
PROHIBITED = ("GEMINI_API_KEY", "zll6796096@gmail.com", "key.json")


def run_capture(args: list[str], *, output: str) -> str:
    try:
        result = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"required command is unavailable: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "no diagnostic output").strip()
        raise SystemExit(f"failed to {output}: {details}") from exc
    return result.stdout


def run(args: list[str], *, output: str) -> None:
    try:
        subprocess.run(args, check=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"required command is unavailable: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"failed to {output} (exit code {exc.returncode})") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def probe_final() -> tuple[dict[str, Any], str]:
    probe_text = run_capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:format_tags:stream=codec_name,codec_type,width,height",
            "-of",
            "json",
            str(FINAL_PATH),
        ],
        output=f"probe final video {FINAL_PATH}",
    )
    try:
        return json.loads(probe_text), probe_text
    except json.JSONDecodeError as exc:
        raise SystemExit("ffprobe returned invalid JSON for the final video") from exc


def verify_media_contract(probe: dict[str, Any]) -> None:
    try:
        duration = float(probe["format"]["duration"])
        streams = probe["streams"]
    except (KeyError, TypeError, ValueError) as exc:
        raise AssertionError(
            "ffprobe output is missing the format duration or stream list"
        ) from exc

    require(
        70 <= duration <= 80,
        f"duration must be between 70 and 80 seconds, got {duration:.3f}s",
    )
    print(f"PASS duration {duration:.3f}s")

    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    require(len(videos) == 1, f"expected exactly one video stream, got {len(videos)}")
    video = videos[0]
    require(
        video.get("codec_name") == "h264",
        f"video codec must be h264, got {video.get('codec_name')!r}",
    )
    dimensions = (video.get("width"), video.get("height"))
    require(
        dimensions == (1920, 1080),
        f"video dimensions must be 1920x1080, got {dimensions[0]}x{dimensions[1]}",
    )
    print("PASS video h264 1920x1080")

    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    require(len(audios) == 1, f"expected exactly one audio stream, got {len(audios)}")
    require(
        audios[0].get("codec_name") == "aac",
        f"audio codec must be aac, got {audios[0].get('codec_name')!r}",
    )
    print("PASS audio aac")


def verify_loudness() -> None:
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(FINAL_PATH),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit("required command is unavailable: ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "no diagnostic output").strip()
        raise SystemExit(f"failed to measure final-video loudness: {details}") from exc

    mean_match = re.search(
        r"mean_volume: (-?\d+(?:\.\d+)?) dB",
        result.stderr,
    )
    max_match = re.search(
        r"max_volume: (-?\d+(?:\.\d+)?) dB",
        result.stderr,
    )
    require(
        mean_match is not None and max_match is not None,
        "ffmpeg volumedetect output did not contain mean_volume and max_volume",
    )
    mean_db = float(mean_match.group(1))
    max_db = float(max_match.group(1))
    require(
        -24 <= mean_db <= -12,
        f"mean volume must be between -24 and -12 dB, got {mean_db:.1f} dB",
    )
    require(max_db <= -1, f"max volume must be at most -1 dB, got {max_db:.1f} dB")
    print(f"PASS loudness mean={mean_db:.1f}dB max={max_db:.1f}dB")


def verify_prohibited_text(probe_text: str) -> None:
    if not RENDERER.exists():
        raise SystemExit(f"missing renderer source for text scan: {RENDERER}")
    scan_text = RENDERER.read_text(encoding="utf-8") + probe_text
    matches = [term for term in PROHIBITED if term in scan_text]
    require(
        not matches,
        f"prohibited text found in renderer source or media metadata: {matches}",
    )
    print("PASS prohibited-text scan")


def generate_review_assets() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    contact = WORK / "contact-sheet.jpg"
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(FINAL_PATH),
            "-vf",
            "fps=1/5,scale=480:-2,tile=4x4:padding=8:margin=8:color=white",
            "-frames:v",
            "1",
            str(contact),
        ],
        output=f"create contact sheet {contact}",
    )
    for second, name in (
        (0, "review-00.jpg"),
        (38, "review-38.jpg"),
        (75, "review-75.jpg"),
    ):
        frame = WORK / name
        run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(second),
                "-i",
                str(FINAL_PATH),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(frame),
            ],
            output=f"extract review frame at {second}s to {frame}",
        )
    return contact


def main() -> None:
    if not FINAL_PATH.exists():
        raise SystemExit(f"missing final video: {FINAL_PATH}")

    probe, probe_text = probe_final()
    verify_media_contract(probe)
    verify_loudness()
    verify_prohibited_text(probe_text)
    contact = generate_review_assets()
    print(f"contact sheet: {contact}")


if __name__ == "__main__":
    main()

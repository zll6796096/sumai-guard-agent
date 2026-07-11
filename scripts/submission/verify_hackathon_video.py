from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from video_manifest import FINAL_PATH, WORK


RENDERER = Path(__file__).with_name("render_hackathon_video.py")
MANIFEST = Path(__file__).with_name("video_manifest.py")
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
            (
                "format=duration:format_tags:"
                "stream=codec_name,codec_type,width,height:stream_tags:"
                "chapter=start_time,end_time:chapter_tags"
            ),
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
    sources = (RENDERER, MANIFEST)
    missing = [path for path in sources if not path.exists()]
    if missing:
        raise SystemExit(f"missing source for prohibited-text scan: {missing}")
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    scan_text = f"{source_text}\n{probe_text}"
    matches = [term for term in PROHIBITED if term in scan_text]
    require(
        not matches,
        (
            "prohibited text found in renderer, manifest, or media metadata: "
            f"{matches}"
        ),
    )
    print("PASS prohibited-text scan")


def verify_image_asset(path: Path, expected_size: tuple[int, int]) -> None:
    require(path.exists(), f"expected review image was not created: {path}")
    require(path.stat().st_size > 0, f"review image is empty: {path}")
    probe_text = run_capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "json",
            str(path),
        ],
        output=f"validate review image {path}",
    )
    try:
        streams = json.loads(probe_text)["streams"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AssertionError(f"invalid ffprobe image output for {path}") from exc
    require(
        len(streams) == 1,
        f"expected one image stream in {path}, got {len(streams)}",
    )
    image = streams[0]
    require(
        image.get("codec_name") == "mjpeg",
        f"review image must be JPEG, got {image.get('codec_name')!r}: {path}",
    )
    actual_size = (image.get("width"), image.get("height"))
    require(
        actual_size == expected_size,
        f"review image must be {expected_size}, got {actual_size}: {path}",
    )


def generate_review_assets() -> tuple[Path, ...]:
    WORK.mkdir(parents=True, exist_ok=True)
    contact = WORK / "contact-sheet.jpg"
    review_specs = (
        (0, WORK / "review-00.jpg"),
        (38, WORK / "review-38.jpg"),
        (75, WORK / "review-75.jpg"),
    )
    review_paths = tuple(path for _, path in review_specs)
    assets = (contact, *review_paths)
    for asset in assets:
        asset.unlink(missing_ok=True)

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
    verify_image_asset(contact, (1960, 1120))
    for second, frame in review_specs:
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
        verify_image_asset(frame, (1920, 1080))
    return assets


def main() -> None:
    if not FINAL_PATH.exists():
        raise SystemExit(f"missing final video: {FINAL_PATH}")

    probe, probe_text = probe_final()
    verify_media_contract(probe)
    verify_loudness()
    verify_prohibited_text(probe_text)
    contact, *review_frames = generate_review_assets()
    print(f"contact sheet: {contact}")
    for frame in review_frames:
        print(f"review frame: {frame}")


if __name__ == "__main__":
    main()

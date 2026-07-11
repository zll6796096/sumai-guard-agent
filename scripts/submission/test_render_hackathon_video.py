from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageStat

import render_hackathon_video as renderer


def make_segment(path: Path, color: str, frequency: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x180:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration=1",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-bf",
            "3",
            "-g",
            "30",
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
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(path),
        ],
        check=True,
    )


def extract_frame_linear(source: Path, second: float, output: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            f"trim=start={second}:end={second + 0.04},setpts=PTS-STARTPTS",
            "-frames:v",
            "1",
            str(output),
        ],
        check=True,
    )


def test_compose_final_reencodes_cleanly_across_b_frame_boundary(
    tmp_path: Path,
) -> None:
    red_segment = tmp_path / "red.mp4"
    blue_segment = tmp_path / "blue.mp4"
    output = tmp_path / "composed.mp4"
    make_segment(red_segment, "red", 440)
    make_segment(blue_segment, "blue", 880)

    renderer.compose_final([red_segment, blue_segment], output)

    probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_name,codec_type",
                "-of",
                "json",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert 1.9 <= float(probe["format"]["duration"]) <= 2.1
    assert {stream["codec_name"] for stream in probe["streams"]} == {"h264", "aac"}

    red_frame = tmp_path / "red.png"
    blue_frame = tmp_path / "blue.png"
    extract_frame_linear(output, 0.5, red_frame)
    extract_frame_linear(output, 1.5, blue_frame)
    with Image.open(red_frame) as image:
        red_mean = ImageStat.Stat(image.convert("RGB")).mean
    with Image.open(blue_frame) as image:
        blue_mean = ImageStat.Stat(image.convert("RGB")).mean

    assert red_mean[0] > 150 and red_mean[0] > red_mean[1] * 3
    assert red_mean[0] > red_mean[2] * 3
    assert blue_mean[2] > 100 and blue_mean[2] > blue_mean[0] * 2
    assert blue_mean[2] > blue_mean[1] * 2

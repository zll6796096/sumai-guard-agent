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


def frame_mean(source: Path, second: float, output: Path) -> list[float]:
    extract_frame_linear(source, second, output)
    with Image.open(output) as image:
        return ImageStat.Stat(image.convert("RGB")).mean


def test_compose_final_uses_concat_filter_and_reencodes(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[list[str]] = []
    moves: list[tuple[Path, Path]] = []
    monkeypatch.setattr(renderer, "run", commands.append)
    monkeypatch.setattr(
        renderer.shutil,
        "move",
        lambda source, destination: moves.append((source, destination)),
    )
    segments = [tmp_path / "first.mp4", tmp_path / "second.mp4"]
    output = tmp_path / "composed.mp4"

    renderer.compose_final(segments, output)

    assert len(commands) == 1
    command = commands[0]
    assert "-filter_complex" in command
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=1" in filter_graph
    assert "-c:v" in command
    assert command[command.index("-c:v") + 1] == "libx264"
    assert not any(
        argument == "-c" and command[index + 1] == "copy"
        for index, argument in enumerate(command[:-1])
    )
    assert moves == [(tmp_path / "composed-rendering.mp4", output)]


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

    samples = {
        "red_midpoint": frame_mean(
            output, 0.5, tmp_path / "red-midpoint.png"
        ),
        "red_before_boundary": frame_mean(
            output, 0.95, tmp_path / "red-before-boundary.png"
        ),
        "blue_at_boundary": frame_mean(
            output, 1.0, tmp_path / "blue-at-boundary.png"
        ),
        "blue_after_boundary": frame_mean(
            output, 1.05, tmp_path / "blue-after-boundary.png"
        ),
        "blue_midpoint": frame_mean(
            output, 1.5, tmp_path / "blue-midpoint.png"
        ),
    }

    for sample in ("red_midpoint", "red_before_boundary"):
        red_mean = samples[sample]
        assert red_mean[0] > 150 and red_mean[0] > red_mean[1] * 3, sample
        assert red_mean[0] > red_mean[2] * 3, sample
    for sample in ("blue_at_boundary", "blue_after_boundary", "blue_midpoint"):
        blue_mean = samples[sample]
        assert blue_mean[2] > 100 and blue_mean[2] > blue_mean[0] * 2, sample
        assert blue_mean[2] > blue_mean[1] * 2, sample

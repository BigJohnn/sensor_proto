from __future__ import annotations

import argparse
import json
import math
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sensor_proto.episode_rerun_viewer import discover_video_streams, load_episode_metadata


@dataclass(slots=True)
class GridLayout:
    columns: int
    rows: int
    tile_width: int
    tile_height: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render all episode camera MP4 files into a tiled mosaic MP4.")
    parser.add_argument("episode_dir", help="Path to the recorded LeRobot episode directory.")
    parser.add_argument(
        "--output",
        help="Output MP4 path. Defaults to <episode_dir>/episode_mosaic.mp4.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="FFmpeg executable to use.",
    )
    parser.add_argument(
        "--columns",
        type=int,
        help="Fixed number of columns in the output mosaic. Rows are derived automatically.",
    )
    parser.add_argument(
        "--tile-width",
        type=int,
        help="Width of each camera tile. Defaults to the recorded video width from metadata.",
    )
    parser.add_argument(
        "--tile-height",
        type=int,
        help="Height of each camera tile. Defaults to the recorded video height from metadata.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the FFmpeg command without running it.",
    )
    return parser.parse_args()


def load_info_payload(episode_dir: str | Path) -> dict:
    info_path = Path(episode_dir).resolve() / "meta" / "info.json"
    if not info_path.exists():
        raise ValueError(f"Episode metadata not found: {info_path}")
    return json.loads(info_path.read_text(encoding="utf-8"))


def discover_tile_size(episode_dir: str | Path, camera_ids: list[str]) -> tuple[int, int]:
    payload = load_info_payload(episode_dir)
    features = payload.get("features", {})
    for camera_id in camera_ids:
        feature = features.get(f"observation.images.{camera_id}", {})
        feature_info = feature.get("info", {})
        width = feature_info.get("video.width")
        height = feature_info.get("video.height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return width, height
    return 640, 480


def choose_grid_layout(
    item_count: int,
    *,
    tile_width: int,
    tile_height: int,
    columns: int | None = None,
) -> GridLayout:
    if item_count < 1:
        raise ValueError("At least one video stream is required to build a mosaic.")
    if tile_width < 1 or tile_height < 1:
        raise ValueError("Tile width and height must be positive integers.")
    if columns is not None:
        if columns < 1:
            raise ValueError("Grid columns must be a positive integer.")
        rows = math.ceil(item_count / columns)
        return GridLayout(columns=columns, rows=rows, tile_width=tile_width, tile_height=tile_height)

    candidate_columns = range(1, item_count + 1)
    best_columns = min(
        candidate_columns,
        key=lambda value: (
            math.ceil(item_count / value) * value - item_count,
            abs(value - math.ceil(item_count / value)),
            math.ceil(item_count / value),
            value,
        ),
    )
    rows = math.ceil(item_count / best_columns)
    return GridLayout(columns=best_columns, rows=rows, tile_width=tile_width, tile_height=tile_height)


def build_filter_complex(stream_count: int, layout: GridLayout) -> str:
    if stream_count < 1:
        raise ValueError("At least one stream is required to build a filter graph.")

    segments: list[str] = []
    inputs: list[str] = []
    for index in range(stream_count):
        segments.append(
            f"[{index}:v]setpts=PTS-STARTPTS,"
            f"scale={layout.tile_width}:{layout.tile_height}:force_original_aspect_ratio=decrease,"
            f"pad={layout.tile_width}:{layout.tile_height}:(ow-iw)/2:(oh-ih)/2:color=black[v{index}]"
        )
        inputs.append(f"[v{index}]")

    positions = [
        f"{(index % layout.columns) * layout.tile_width}_{(index // layout.columns) * layout.tile_height}"
        for index in range(stream_count)
    ]
    segments.append(
        "".join(inputs)
        + f"xstack=inputs={stream_count}:layout={'|'.join(positions)}:fill=black[vout]"
    )
    return ";".join(segments)


def default_output_path(episode_dir: str | Path) -> Path:
    return Path(episode_dir).resolve() / "episode_mosaic.mp4"


def build_ffmpeg_command(
    episode_dir: str | Path,
    *,
    output_path: str | Path | None,
    ffmpeg_bin: str,
    overwrite: bool,
    columns: int | None,
    tile_width: int | None,
    tile_height: int | None,
) -> tuple[list[str], Path]:
    metadata = load_episode_metadata(episode_dir)
    streams = discover_video_streams(metadata)
    detected_tile_width, detected_tile_height = discover_tile_size(episode_dir, metadata.camera_ids)
    layout = choose_grid_layout(
        len(streams),
        columns=columns,
        tile_width=tile_width or detected_tile_width,
        tile_height=tile_height or detected_tile_height,
    )
    filter_complex = build_filter_complex(len(streams), layout)
    resolved_output_path = Path(output_path).resolve() if output_path else default_output_path(episode_dir)

    command = [ffmpeg_bin, "-hide_banner", "-loglevel", "warning", "-y" if overwrite else "-n"]
    for stream in streams:
        command.extend(["-i", str(stream.path)])
    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-an",
            "-r",
            f"{metadata.fps:g}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(resolved_output_path),
        ]
    )
    return command, resolved_output_path


def main() -> None:
    args = parse_args()
    command, output_path = build_ffmpeg_command(
        args.episode_dir,
        output_path=args.output,
        ffmpeg_bin=args.ffmpeg_bin,
        overwrite=args.overwrite,
        columns=args.columns,
        tile_width=args.tile_width,
        tile_height=args.tile_height,
    )

    if args.dry_run:
        print(shlex.join(command))
        return

    subprocess.run(command, check=True)
    print(output_path)


if __name__ == "__main__":
    main()

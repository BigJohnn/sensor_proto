from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from sensor_proto.preview import compute_grid_layout


@dataclass(slots=True)
class EpisodeMetadata:
    root_dir: Path
    fps: float
    camera_ids: list[str]
    total_frames: int


@dataclass(slots=True)
class VideoStream:
    camera_id: str
    path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualize a recorded LeRobot episode with rerun-sdk on the host.")
    parser.add_argument("episode_dir", help="Path to the recorded LeRobot episode directory.")
    parser.add_argument("--app-id", default="sensor-proto-episode-viewer", help="Rerun application id.")
    parser.add_argument("--entity-root", default="episode", help="Root entity path in Rerun.")
    parser.add_argument("--max-width", type=int, default=1600, help="Maximum mosaic width in pixels.")
    parser.add_argument("--max-height", type=int, default=900, help="Maximum mosaic height in pixels.")
    parser.add_argument("--sleep-ms", type=int, default=0, help="Optional delay after each logged frame.")
    parser.add_argument(
        "--spawn",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Spawn a local Rerun viewer process.",
    )
    return parser.parse_args()


def load_episode_metadata(episode_dir: str | Path) -> EpisodeMetadata:
    root_dir = Path(episode_dir).resolve()
    info_path = root_dir / "meta" / "info.json"
    if not info_path.exists():
        raise ValueError(f"Episode metadata not found: {info_path}")
    payload = json.loads(info_path.read_text(encoding="utf-8"))
    features = payload.get("features", {})
    camera_ids = sorted(
        feature_name.removeprefix("observation.images.")
        for feature_name, feature_spec in features.items()
        if feature_name.startswith("observation.images.") and feature_spec.get("dtype") in {"video", "image"}
    )
    if not camera_ids:
        raise ValueError(f"No image/video camera features found in {info_path}")
    return EpisodeMetadata(
        root_dir=root_dir,
        fps=float(payload.get("fps", 30.0)),
        camera_ids=camera_ids,
        total_frames=int(payload.get("total_frames", 0)),
    )


def discover_video_streams(metadata: EpisodeMetadata) -> list[VideoStream]:
    streams: list[VideoStream] = []
    for camera_id in metadata.camera_ids:
        video_path = metadata.root_dir / "videos" / f"observation.images.{camera_id}" / "chunk-000" / "file-000.mp4"
        if not video_path.exists():
            raise ValueError(f"Expected video for {camera_id} at {video_path}")
        streams.append(VideoStream(camera_id=camera_id, path=video_path))
    return streams


def build_mosaic(frames: dict[str, object], camera_order: list[str], max_width: int, max_height: int):
    if not camera_order:
        raise ValueError("camera_order must not be empty.")
    cv2 = _load_cv2_module()
    np = _load_numpy_module()
    first_frame = frames[camera_order[0]]
    frame_height, frame_width = first_frame.shape[:2]
    layout = compute_grid_layout(
        frame_width=frame_width,
        frame_height=frame_height,
        camera_count=len(camera_order),
        max_width=max_width,
        max_height=max_height,
    )
    canvas = np.zeros((layout.canvas_height, layout.canvas_width, 3), dtype=np.uint8)
    canvas[:] = (9, 17, 26)
    gap_px = 12
    header_px = 72
    cv2.putText(
        canvas,
        f"cams={len(camera_order)}  size={frame_width}x{frame_height}",
        (gap_px, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (236, 242, 248),
        2,
        cv2.LINE_AA,
    )
    for index, camera_id in enumerate(camera_order):
        row = index // layout.cols
        col = index % layout.cols
        x = gap_px + col * (layout.cell_width + gap_px)
        y = header_px + gap_px + row * (layout.cell_height + gap_px)
        frame = frames[camera_id]
        resized = cv2.resize(frame, (layout.cell_width, layout.cell_height), interpolation=cv2.INTER_AREA)
        canvas[y : y + layout.cell_height, x : x + layout.cell_width] = resized
        cv2.rectangle(canvas, (x, y), (x + layout.cell_width, y + layout.cell_height), (83, 209, 201), 1)
        cv2.putText(
            canvas,
            camera_id,
            (x + 8, y + 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 209, 102),
            2,
            cv2.LINE_AA,
        )
    return canvas


def _load_cv2_module():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on host environment
        raise RuntimeError("Episode Rerun viewer requires cv2 on the host.") from exc
    return cv2


def _load_numpy_module():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on host environment
        raise RuntimeError("Episode Rerun viewer requires numpy on the host.") from exc
    return np


def _load_rerun_module():
    try:
        import rerun as rr
    except ImportError as exc:  # pragma: no cover - depends on host environment
        raise RuntimeError("Episode Rerun viewer requires rerun-sdk on the host.") from exc
    return rr


def main() -> None:
    args = parse_args()
    metadata = load_episode_metadata(args.episode_dir)
    streams = discover_video_streams(metadata)
    rr = _load_rerun_module()
    cv2 = _load_cv2_module()

    rr.init(args.app_id, spawn=args.spawn)

    captures = {stream.camera_id: cv2.VideoCapture(str(stream.path)) for stream in streams}
    try:
        for camera_id, capture in captures.items():
            if not capture.isOpened():
                raise RuntimeError(f"Failed to open video for {camera_id}: {captures[camera_id]}")

        frame_index = 0
        while True:
            frames: dict[str, object] = {}
            for stream in streams:
                ok, frame = captures[stream.camera_id].read()
                if not ok:
                    return
                frames[stream.camera_id] = frame

            rr.set_time_sequence("frame", frame_index)
            rr.set_time_seconds("time", frame_index / metadata.fps)

            for camera_id in metadata.camera_ids:
                rr.log(f"{args.entity_root}/cameras/{camera_id}", rr.Image(frames[camera_id][:, :, ::-1]))

            mosaic = build_mosaic(frames, metadata.camera_ids, max_width=args.max_width, max_height=args.max_height)
            rr.log(f"{args.entity_root}/mosaic", rr.Image(mosaic[:, :, ::-1]))

            frame_index += 1
            if args.sleep_ms > 0:
                time.sleep(args.sleep_ms / 1000.0)
    finally:
        for capture in captures.values():
            capture.release()


if __name__ == "__main__":
    main()

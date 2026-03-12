from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


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


def build_blueprint(entity_root: str, camera_ids: list[str]):
    rrb = _load_rerun_blueprint_module()
    views = [
        rrb.Spatial2DView(
            origin=f"{entity_root}/cameras/{camera_id}",
            name=camera_id,
        )
        for camera_id in camera_ids
    ]
    return rrb.Blueprint(
        rrb.Grid(contents=views, grid_columns=max(1, min(3, len(views)))),
        rrb.TimePanel(timeline="time", playback_speed=1.0),
    )


def _load_rerun_module():
    try:
        import rerun as rr
    except ImportError as exc:  # pragma: no cover - depends on host environment
        raise RuntimeError("Episode Rerun viewer requires rerun-sdk on the host.") from exc
    return rr


def _load_rerun_blueprint_module():
    try:
        import rerun.blueprint as rrb
    except ImportError as exc:  # pragma: no cover - depends on host environment
        raise RuntimeError("Episode Rerun viewer requires rerun-sdk blueprint support on the host.") from exc
    return rrb


def main() -> None:
    args = parse_args()
    metadata = load_episode_metadata(args.episode_dir)
    streams = discover_video_streams(metadata)
    rr = _load_rerun_module()

    rr.init(args.app_id, spawn=args.spawn)
    rr.send_blueprint(build_blueprint(args.entity_root, metadata.camera_ids))

    for stream in streams:
        entity_path = f"{args.entity_root}/cameras/{stream.camera_id}"
        video_asset = rr.AssetVideo(path=stream.path)
        rr.log(entity_path, video_asset, static=True)
        frame_timestamps_ns = video_asset.read_frame_timestamps_nanos()
        frame_count = len(frame_timestamps_ns)
        rr.send_columns(
            entity_path,
            indexes=[
                rr.TimeColumn("time", duration=1e-9 * frame_timestamps_ns),
            ],
            columns=rr.VideoFrameReference.columns_nanos(frame_timestamps_ns),
        )


if __name__ == "__main__":
    main()

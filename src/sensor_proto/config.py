from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CameraConfig:
    id: str
    kind: str
    model: str
    fps: int
    width: int
    height: int
    serial: str | None = None
    max_frames: int | None = None
    mock_payload_size: int = 0
    mock_jitter_ms: float = 0.0
    mock_fail_after_frames: int | None = None
    mock_timestamp_offset_ms: float = 0.0
    mock_timestamp_drift_ppm: float = 0.0
    mock_sync_group: str | None = None
    capture_image_data: bool = False
    seed: int = 0


@dataclass(slots=True)
class SyncConfig:
    enabled: bool = True
    strategy: str = "device-clock-soft-sync"
    tolerance_ms: float = 12.0
    max_buffered_frames: int = 4
    reference_camera_id: str | None = None
    hardware_sync_mode: str = "disabled"


@dataclass(slots=True)
class StreamConfig:
    host: str = "0.0.0.0"
    port: int = 8787
    recent_sets: int = 4
    client_refresh_ms: int = 250
    preview_max_width: int = 1280
    preview_max_height: int = 720
    preview_jpeg_quality: int = 72


@dataclass(slots=True)
class RecordingConfig:
    enabled: bool = False
    format: str = "lerobot_v3"
    root_dir: str | None = None
    repo_id: str = "local/sensor-proto"
    task: str = "synchronized-multi-camera-observation"
    robot_type: str = "camera-rig"
    fps: int | None = None
    use_videos: bool = True
    queue_maxsize: int = 32
    overflow_policy: str = "fail_recording_keep_stream"
    video_codec: str = "h264"
    encoder_queue_maxsize: int = 30
    encoder_threads: int | None = None


@dataclass(slots=True)
class RunConfig:
    cameras: list[CameraConfig]
    duration_s: float
    queue_size: int = 32
    processing_delay_ms: float = 0.0
    report_path: str | None = None
    sync: SyncConfig = field(default_factory=SyncConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)


def load_run_config(path: str | Path) -> RunConfig:
    raw = load_run_config_payload(path)
    cameras = [CameraConfig(**camera) for camera in raw.get("cameras", [])]
    if not cameras:
        raise ValueError("Run config must define at least one camera.")
    sync_raw = raw.get("sync", {})
    stream_raw = raw.get("stream", {})
    recording_raw = raw.get("recording", {})
    return RunConfig(
        cameras=cameras,
        duration_s=float(raw.get("duration_s", 10.0)),
        queue_size=int(raw.get("queue_size", 32)),
        processing_delay_ms=float(raw.get("processing_delay_ms", 0.0)),
        report_path=raw.get("report_path"),
        sync=SyncConfig(
            enabled=bool(sync_raw.get("enabled", True)),
            strategy=str(sync_raw.get("strategy", "device-clock-soft-sync")),
            tolerance_ms=float(sync_raw.get("tolerance_ms", 12.0)),
            max_buffered_frames=int(sync_raw.get("max_buffered_frames", 4)),
            reference_camera_id=sync_raw.get("reference_camera_id"),
            hardware_sync_mode=str(sync_raw.get("hardware_sync_mode", "disabled")),
        ),
        stream=StreamConfig(
            host=str(stream_raw.get("host", "0.0.0.0")),
            port=int(stream_raw.get("port", 8787)),
            recent_sets=int(stream_raw.get("recent_sets", 4)),
            client_refresh_ms=int(stream_raw.get("client_refresh_ms", 250)),
            preview_max_width=int(stream_raw.get("preview_max_width", 1280)),
            preview_max_height=int(stream_raw.get("preview_max_height", 720)),
            preview_jpeg_quality=int(stream_raw.get("preview_jpeg_quality", 72)),
        ),
        recording=RecordingConfig(
            enabled=bool(recording_raw.get("enabled", False)),
            format=str(recording_raw.get("format", "lerobot_v3")),
            root_dir=recording_raw.get("root_dir"),
            repo_id=str(recording_raw.get("repo_id", "local/sensor-proto")),
            task=str(recording_raw.get("task", "synchronized-multi-camera-observation")),
            robot_type=str(recording_raw.get("robot_type", "camera-rig")),
            fps=int(recording_raw["fps"]) if recording_raw.get("fps") is not None else None,
            use_videos=bool(recording_raw.get("use_videos", True)),
            queue_maxsize=int(recording_raw.get("queue_maxsize", 32)),
            overflow_policy=str(recording_raw.get("overflow_policy", "fail_recording_keep_stream")),
            video_codec=str(recording_raw.get("video_codec", "h264")),
            encoder_queue_maxsize=int(recording_raw.get("encoder_queue_maxsize", 30)),
            encoder_threads=(
                int(recording_raw["encoder_threads"])
                if recording_raw.get("encoder_threads") is not None
                else None
            ),
        ),
    )


def ensure_parent_dir(path: str | Path | None) -> None:
    if not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def load_run_config_payload(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Run config root must be a JSON object.")
    return raw


def write_run_config_payload(path: str | Path, payload: Mapping[str, Any]) -> None:
    ensure_parent_dir(path)
    Path(path).write_text(
        json.dumps(dict(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

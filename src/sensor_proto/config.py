from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


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
class RunConfig:
    cameras: list[CameraConfig]
    duration_s: float
    queue_size: int = 32
    processing_delay_ms: float = 0.0
    report_path: str | None = None
    sync: SyncConfig = field(default_factory=SyncConfig)


def load_run_config(path: str | Path) -> RunConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cameras = [CameraConfig(**camera) for camera in raw.get("cameras", [])]
    if not cameras:
        raise ValueError("Run config must define at least one camera.")
    sync_raw = raw.get("sync", {})
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
    )


def ensure_parent_dir(path: str | Path | None) -> None:
    if not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)

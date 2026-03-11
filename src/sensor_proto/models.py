from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class Frame:
    camera_id: str
    camera_kind: str
    sequence: int
    created_at: float
    payload_size: int
    host_received_at: float | None = None
    device_timestamp_ms: float | None = None
    timestamp_domain: str | None = None
    frame_counter: int | None = None
    sensor_serial: str | None = None
    hardware_sync_group: str | None = None
    normalized_timestamp_s: float | None = None

    def __post_init__(self) -> None:
        if self.host_received_at is None:
            self.host_received_at = self.created_at


@dataclass(slots=True)
class CameraMetrics:
    produced: int = 0
    processed: int = 0
    dropped: int = 0
    failed: bool = False
    failure_reason: str | None = None
    total_latency_ms: float = 0.0
    max_latency_ms: float = 0.0

    def record_latency(self, latency_ms: float) -> None:
        self.total_latency_ms += latency_ms
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["avg_latency_ms"] = round(self.total_latency_ms / self.processed, 3) if self.processed else 0.0
        return data


@dataclass(slots=True)
class SyncMetrics:
    enabled: bool
    strategy: str
    tolerance_ms: float
    reference_camera_id: str | None = None
    hardware_sync_mode: str = "disabled"
    aligned_sets: int = 0
    incomplete_sets: int = 0
    dropped_frames: int = 0
    pending_frames: int = 0
    total_skew_ms: float = 0.0
    max_skew_ms: float = 0.0
    per_camera_dropped: dict[str, int] = field(default_factory=dict)
    per_camera: dict[str, CameraSyncMetrics] = field(default_factory=dict)
    warnings: list[SyncWarning] = field(default_factory=list)

    def record_aligned(self, skew_ms: float) -> None:
        self.aligned_sets += 1
        self.total_skew_ms += skew_ms
        self.max_skew_ms = max(self.max_skew_ms, skew_ms)

    def record_incomplete(self, camera_id: str) -> None:
        self.incomplete_sets += 1
        self.dropped_frames += 1
        self.per_camera_dropped[camera_id] = self.per_camera_dropped.get(camera_id, 0) + 1
        if camera_id in self.per_camera:
            self.per_camera[camera_id].record_dropped()

    def record_warning(self, camera_id: str, code: str, message: str) -> None:
        self.warnings.append(SyncWarning(camera_id=camera_id, code=code, message=message))

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["avg_skew_ms"] = round(self.total_skew_ms / self.aligned_sets, 3) if self.aligned_sets else 0.0
        return data


@dataclass(slots=True)
class CameraSyncMetrics:
    observed_frames: int = 0
    aligned_frames: int = 0
    dropped_frames: int = 0
    uses_host_clock_fallback: bool = False
    total_offset_ms: float = 0.0
    max_abs_offset_ms: float = 0.0
    first_offset_ms: float | None = None
    last_offset_ms: float | None = None
    first_reference_timestamp_s: float | None = None
    last_reference_timestamp_s: float | None = None

    def record_observed(self, uses_host_clock_fallback: bool) -> None:
        self.observed_frames += 1
        self.uses_host_clock_fallback = self.uses_host_clock_fallback or uses_host_clock_fallback

    def record_dropped(self) -> None:
        self.dropped_frames += 1

    def record_alignment(self, offset_ms: float, reference_timestamp_s: float) -> None:
        self.aligned_frames += 1
        self.total_offset_ms += offset_ms
        self.max_abs_offset_ms = max(self.max_abs_offset_ms, abs(offset_ms))
        if self.first_offset_ms is None:
            self.first_offset_ms = offset_ms
            self.first_reference_timestamp_s = reference_timestamp_s
        self.last_offset_ms = offset_ms
        self.last_reference_timestamp_s = reference_timestamp_s

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["avg_offset_ms"] = round(self.total_offset_ms / self.aligned_frames, 3) if self.aligned_frames else 0.0
        drift_ms = 0.0
        drift_ppm = 0.0
        if (
            self.first_offset_ms is not None
            and self.last_offset_ms is not None
            and self.first_reference_timestamp_s is not None
            and self.last_reference_timestamp_s is not None
        ):
            drift_ms = self.last_offset_ms - self.first_offset_ms
            elapsed_ms = (self.last_reference_timestamp_s - self.first_reference_timestamp_s) * 1000.0
            if elapsed_ms > 0.0:
                drift_ppm = (drift_ms / elapsed_ms) * 1_000_000.0
        data["drift_ms"] = round(drift_ms, 3)
        data["drift_ppm"] = round(drift_ppm, 3)
        return data


@dataclass(slots=True)
class SyncWarning:
    camera_id: str
    code: str
    message: str


@dataclass(slots=True)
class RunReport:
    duration_s: float
    queue_size: int
    processing_delay_ms: float
    cameras: dict[str, CameraMetrics] = field(default_factory=dict)
    sync: SyncMetrics | None = None

    def as_dict(self) -> dict[str, object]:
        payload = {
            "duration_s": self.duration_s,
            "queue_size": self.queue_size,
            "processing_delay_ms": self.processing_delay_ms,
            "cameras": {camera_id: metric.as_dict() for camera_id, metric in self.cameras.items()},
        }
        if self.sync is not None:
            payload["sync"] = self.sync.as_dict()
        return payload

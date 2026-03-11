from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from sensor_proto.config import RunConfig
from sensor_proto.models import CameraSyncMetrics, Frame, SyncMetrics


@dataclass(slots=True)
class _ClockTracker:
    device_origin_ms: float
    host_origin_s: float
    correction_s: float = 0.0

    def normalize(self, device_timestamp_ms: float, host_received_at: float) -> float:
        predicted_host_s = self.host_origin_s + (device_timestamp_ms - self.device_origin_ms) / 1000.0
        observed_correction_s = host_received_at - predicted_host_s
        self.correction_s = (self.correction_s * 0.9) + (observed_correction_s * 0.1)
        return predicted_host_s + self.correction_s


class FrameSynchronizer:
    def __init__(self, config: RunConfig) -> None:
        self._camera_ids = [camera.id for camera in config.cameras]
        self._reference_camera_id = config.sync.reference_camera_id or self._camera_ids[0]
        self._tolerance_s = max(config.sync.tolerance_ms, 0.0) / 1000.0
        self._max_buffered_frames = max(config.sync.max_buffered_frames, 1)
        self._clock_trackers: dict[str, _ClockTracker] = {}
        self._pending: dict[str, deque[Frame]] = {camera_id: deque() for camera_id in self._camera_ids}
        self.metrics = SyncMetrics(
            enabled=config.sync.enabled and len(self._camera_ids) > 1,
            strategy=config.sync.strategy,
            tolerance_ms=config.sync.tolerance_ms,
            reference_camera_id=self._reference_camera_id,
            hardware_sync_mode=config.sync.hardware_sync_mode,
            per_camera={camera_id: CameraSyncMetrics() for camera_id in self._camera_ids},
        )

    def observe(self, frame: Frame) -> None:
        if not self.metrics.enabled:
            return
        self.metrics.per_camera[frame.camera_id].record_observed(frame.device_timestamp_ms is None)
        normalized = self._normalize(frame)
        self._pending[frame.camera_id].append(normalized)
        self._trim_buffers()
        self._match_frames()

    def finalize(self) -> SyncMetrics:
        if self.metrics.enabled:
            self.metrics.pending_frames = sum(len(buffer) for buffer in self._pending.values())
            self._emit_warnings()
        return self.metrics

    def _normalize(self, frame: Frame) -> Frame:
        host_received_at = frame.host_received_at or frame.created_at
        if frame.device_timestamp_ms is None:
            frame.normalized_timestamp_s = host_received_at
            return frame
        tracker = self._clock_trackers.get(frame.camera_id)
        if tracker is None:
            tracker = _ClockTracker(
                device_origin_ms=frame.device_timestamp_ms,
                host_origin_s=host_received_at,
            )
            self._clock_trackers[frame.camera_id] = tracker
            frame.normalized_timestamp_s = host_received_at
            return frame
        frame.normalized_timestamp_s = tracker.normalize(frame.device_timestamp_ms, host_received_at)
        return frame

    def _trim_buffers(self) -> None:
        for camera_id, buffer in self._pending.items():
            while len(buffer) > self._max_buffered_frames:
                buffer.popleft()
                self.metrics.record_incomplete(camera_id)

    def _match_frames(self) -> None:
        while all(self._pending[camera_id] for camera_id in self._camera_ids):
            head_frames = {camera_id: self._pending[camera_id][0] for camera_id in self._camera_ids}
            timestamps = {
                camera_id: self._frame_timestamp_s(frame)
                for camera_id, frame in head_frames.items()
            }
            reference_timestamp_s = timestamps[self._reference_camera_id]
            earliest_camera_id = min(timestamps, key=timestamps.get)
            latest_timestamp_s = max(timestamps.values())
            earliest_timestamp_s = timestamps[earliest_camera_id]
            skew_s = latest_timestamp_s - earliest_timestamp_s

            if skew_s <= self._tolerance_s:
                for camera_id in self._camera_ids:
                    offset_ms = (timestamps[camera_id] - reference_timestamp_s) * 1000.0
                    self.metrics.per_camera[camera_id].record_alignment(offset_ms, reference_timestamp_s)
                    self._pending[camera_id].popleft()
                self.metrics.record_aligned(skew_s * 1000.0)
                continue

            self._pending[earliest_camera_id].popleft()
            self.metrics.record_incomplete(earliest_camera_id)

    @staticmethod
    def _frame_timestamp_s(frame: Frame) -> float:
        return frame.normalized_timestamp_s or frame.host_received_at or frame.created_at

    def _emit_warnings(self) -> None:
        for camera_id, camera_metrics in self.metrics.per_camera.items():
            if camera_metrics.uses_host_clock_fallback:
                self.metrics.record_warning(
                    camera_id,
                    "host_clock_fallback",
                    f"{camera_id} is missing device timestamps and is falling back to host receive time.",
                )
            if camera_metrics.dropped_frames >= 3 and camera_metrics.dropped_frames > camera_metrics.aligned_frames * 0.2:
                self.metrics.record_warning(
                    camera_id,
                    "sync_window_drop",
                    (
                        f"{camera_id} fell out of the sync window {camera_metrics.dropped_frames} times "
                        f"across {camera_metrics.aligned_frames} aligned frames."
                    ),
                )
            if abs(camera_metrics.as_dict()["drift_ppm"]) > 1_000.0:
                self.metrics.record_warning(
                    camera_id,
                    "clock_drift",
                    f"{camera_id} shows estimated clock drift above 1000 ppm.",
                )

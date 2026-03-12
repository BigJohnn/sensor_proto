from __future__ import annotations

import importlib
import inspect
import json
import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sensor_proto.config import CameraConfig, RunConfig
from sensor_proto.models import AlignedFrameSet, Frame


class RecordingError(RuntimeError):
    pass


@dataclass(slots=True)
class RecordingSession:
    root_dir: Path
    repo_id: str
    fps: int
    camera_features: dict[str, str]
    episode_start_timestamp_s: float | None = None
    aligned_timestamps_s: list[float] | None = None


@dataclass(slots=True)
class RecordingStatus:
    enabled: bool
    active: bool
    failed: bool
    overflow_policy: str | None
    queue_maxsize: int | None
    queue_size: int
    queue_high_watermark: int
    submitted_sets: int
    written_sets: int
    dropped_sets: int
    queue_full_events: int
    first_failure_at_set: int | None
    last_error: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "active": self.active,
            "failed": self.failed,
            "overflow_policy": self.overflow_policy,
            "queue_maxsize": self.queue_maxsize,
            "queue_size": self.queue_size,
            "queue_high_watermark": self.queue_high_watermark,
            "submitted_sets": self.submitted_sets,
            "written_sets": self.written_sets,
            "dropped_sets": self.dropped_sets,
            "queue_full_events": self.queue_full_events,
            "first_failure_at_set": self.first_failure_at_set,
            "last_error": self.last_error,
        }


class RecorderBackend(Protocol):
    def record(self, aligned_set: AlignedFrameSet) -> None: ...

    def close(self) -> None: ...


def sanitize_camera_feature_name(camera_id: str) -> str:
    candidate = re.sub(r"[^0-9A-Za-z_]+", "_", camera_id).strip("_").lower()
    if not candidate:
        candidate = "camera"
    if candidate[0].isdigit():
        candidate = f"camera_{candidate}"
    return candidate


def build_camera_feature_map(camera_ids: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used_names: set[str] = set()
    for camera_id in camera_ids:
        base_name = sanitize_camera_feature_name(camera_id)
        candidate = base_name
        suffix = 2
        while candidate in used_names:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(candidate)
        mapping[camera_id] = f"observation.images.{candidate}"
    return mapping


def resolve_recording_fps(config: RunConfig) -> int:
    if config.recording.fps is not None:
        return int(config.recording.fps)
    unique_fps = {int(camera.fps) for camera in config.cameras}
    if len(unique_fps) != 1:
        raise RecordingError(
            "Recording LeRobot v3 requires a single dataset fps. "
            "Set recording.fps explicitly when camera fps differ."
        )
    return next(iter(unique_fps))


def build_recording_features(
    cameras: list[CameraConfig],
    camera_features: dict[str, str],
    *,
    use_videos: bool,
) -> dict[str, dict[str, object]]:
    dtype = "video" if use_videos else "image"
    return {
        camera_features[camera.id]: {
            "dtype": dtype,
            "shape": (camera.height, camera.width, 3),
            "names": ("height", "width", "channel"),
        }
        for camera in cameras
    }


class LeRobotRecorder:
    def __init__(self, config: RunConfig) -> None:
        if not config.recording.enabled:
            raise RecordingError("LeRobotRecorder requires recording.enabled=true.")
        if config.recording.format != "lerobot_v3":
            raise RecordingError(f"Unsupported recording format: {config.recording.format}")

        self._config = config
        self._numpy = self._load_numpy_module()
        self._dataset = None
        self._saved_episode = False
        self._finalized = False
        self._recorded_sets = 0
        self._validate_capture_config()

        root_dir = Path(config.recording.root_dir or "artifacts/lerobot-dataset").resolve()
        root_dir.parent.mkdir(parents=True, exist_ok=True)
        camera_features = build_camera_feature_map([camera.id for camera in config.cameras])
        self.session = RecordingSession(
            root_dir=root_dir,
            repo_id=config.recording.repo_id,
            fps=resolve_recording_fps(config),
            camera_features=camera_features,
            aligned_timestamps_s=[],
        )
        self._dataset = self._create_dataset()

    def record(self, aligned_set: AlignedFrameSet) -> None:
        dataset = self._require_dataset()
        if self.session.episode_start_timestamp_s is None:
            self.session.episode_start_timestamp_s = aligned_set.reference_timestamp_s
        relative_timestamp_s = max(0.0, aligned_set.reference_timestamp_s - self.session.episode_start_timestamp_s)
        payload: dict[str, Any] = {"task": self._config.recording.task}
        for camera in self._config.cameras:
            frame = aligned_set.frames.get(camera.id)
            if frame is None:
                raise RecordingError(f"Aligned frame set {aligned_set.set_id} is missing camera {camera.id}.")
            payload[self.session.camera_features[camera.id]] = self._frame_to_rgb_array(frame)
        dataset.add_frame(payload)
        if self.session.aligned_timestamps_s is not None:
            self.session.aligned_timestamps_s.append(relative_timestamp_s)
        self._recorded_sets += 1

    def close(self) -> None:
        dataset = self._dataset
        if dataset is None:
            return
        if self._recorded_sets > 0 and not self._saved_episode:
            self._call_with_supported_kwargs(dataset.save_episode, {"task": self._config.recording.task})
            self._saved_episode = True
        if not self._finalized:
            finalize = getattr(dataset, "finalize", None) or getattr(dataset, "consolidate", None)
            if finalize is not None:
                finalize()
            self._finalized = True
        self._write_aligned_timestamps_sidecar()

    def _create_dataset(self):
        dataset_class = self._load_dataset_class()
        create_kwargs: dict[str, object] = {
            "repo_id": self.session.repo_id,
            "fps": self.session.fps,
            "robot_type": self._config.recording.robot_type,
            "features": build_recording_features(
                self._config.cameras,
                self.session.camera_features,
                use_videos=self._config.recording.use_videos,
            ),
            "use_videos": self._config.recording.use_videos,
        }
        create_signature = inspect.signature(dataset_class.create)
        create_parameters = create_signature.parameters
        create_supports_var_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in create_parameters.values()
        )
        if create_supports_var_kwargs or "root" in create_parameters:
            create_kwargs["root"] = self.session.root_dir
        elif "root_dir" in create_parameters:
            create_kwargs["root_dir"] = self.session.root_dir
        dataset = self._call_with_supported_kwargs(dataset_class.create, create_kwargs)
        if self._config.recording.use_videos:
            self._enable_streaming_video_encoding(dataset)
        return dataset

    def _require_dataset(self):
        if self._dataset is None:
            raise RecordingError("LeRobot dataset is not initialized.")
        return self._dataset

    def _write_aligned_timestamps_sidecar(self) -> None:
        timestamps_s = self.session.aligned_timestamps_s
        if not timestamps_s:
            return
        sidecar_path = self.session.root_dir / "meta" / "aligned_timestamps.json"
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "timeline": "aligned_reference_timestamp_s",
            "unit": "seconds_from_episode_start",
            "frame_count": self._recorded_sets,
            "timestamps_s": timestamps_s,
        }
        sidecar_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _frame_to_rgb_array(self, frame: Frame):
        if frame.image_data is None or frame.width is None or frame.height is None:
            raise RecordingError(f"{frame.camera_id} does not include image data for recording.")
        if frame.pixel_format != "bgr8":
            raise RecordingError(f"{frame.camera_id} has unsupported pixel format {frame.pixel_format!r}.")
        expected_size = frame.width * frame.height * 3
        if len(frame.image_data) != expected_size:
            raise RecordingError(
                f"{frame.camera_id} image buffer size {len(frame.image_data)} does not match expected {expected_size}."
            )
        image = self._numpy.frombuffer(frame.image_data, dtype=self._numpy.uint8).reshape((frame.height, frame.width, 3))
        return image[:, :, ::-1].copy()

    def _validate_capture_config(self) -> None:
        for camera in self._config.cameras:
            if not camera.capture_image_data:
                raise RecordingError(
                    f"Camera {camera.id} must set capture_image_data=true when recording LeRobot v3 datasets."
                )

    @staticmethod
    def _call_with_supported_kwargs(callable_obj, kwargs: dict[str, object]):
        signature = inspect.signature(callable_obj)
        supports_var_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
        )
        if supports_var_kwargs:
            return callable_obj(**kwargs)
        accepted_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in signature.parameters and signature.parameters[key].kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        return callable_obj(**accepted_kwargs)

    @staticmethod
    def _load_dataset_class():
        module_paths = (
            "lerobot.common.datasets.lerobot_dataset",
            "lerobot.datasets.lerobot_dataset",
        )
        for module_path in module_paths:
            try:
                module = importlib.import_module(module_path)
            except ImportError:
                continue
            dataset_class = getattr(module, "LeRobotDataset", None)
            if dataset_class is not None:
                return dataset_class
        raise RecordingError(
            "LeRobot is not installed. Install the official `lerobot` package to enable LeRobot v3 recording."
        )

    @staticmethod
    def _load_video_utils_module():
        module_paths = (
            "lerobot.common.datasets.video_utils",
            "lerobot.datasets.video_utils",
        )
        for module_path in module_paths:
            try:
                return importlib.import_module(module_path)
            except ImportError:
                continue
        raise RecordingError(
            "LeRobot video utilities are not available. Install the official `lerobot` package to enable video recording."
        )

    def _enable_streaming_video_encoding(self, dataset: Any) -> None:
        video_utils = self._load_video_utils_module()
        encoder_class = getattr(video_utils, "StreamingVideoEncoder", None)
        if encoder_class is None:
            raise RecordingError("LeRobot StreamingVideoEncoder is not available in the runtime environment.")
        resolve_vcodec = getattr(video_utils, "resolve_vcodec", None)
        vcodec = self._config.recording.video_codec
        if callable(resolve_vcodec):
            vcodec = resolve_vcodec(vcodec)
        dataset.vcodec = vcodec
        dataset._encoder_threads = self._config.recording.encoder_threads
        dataset._streaming_encoder = self._call_with_supported_kwargs(
            encoder_class,
            {
                "fps": self.session.fps,
                "vcodec": vcodec,
                "queue_maxsize": self._config.recording.encoder_queue_maxsize,
                "encoder_threads": self._config.recording.encoder_threads,
            },
        )

    @staticmethod
    def _load_numpy_module():
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - depends on runtime environment
            raise RecordingError("Recording LeRobot v3 datasets requires numpy in the runtime environment.") from exc
        return np


class RecordingSink:
    _supported_overflow_policies = {"fail_recording_keep_stream"}

    def __init__(
        self,
        recorder: RecorderBackend,
        *,
        queue_maxsize: int,
        overflow_policy: str,
    ) -> None:
        if overflow_policy not in self._supported_overflow_policies:
            raise RecordingError(f"Unsupported recording overflow policy: {overflow_policy}")
        self._recorder = recorder
        self._queue_maxsize = max(queue_maxsize, 1)
        self._overflow_policy = overflow_policy
        self._queue: queue.Queue[AlignedFrameSet] = queue.Queue(maxsize=self._queue_maxsize)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._submitted_sets = 0
        self._written_sets = 0
        self._dropped_sets = 0
        self._queue_full_events = 0
        self._queue_high_watermark = 0
        self._failed = False
        self._first_failure_at_set: int | None = None
        self._last_error: str | None = None
        self._worker = threading.Thread(target=self._run_worker, name="recording-sink-worker", daemon=True)
        self._worker.start()

    @classmethod
    def disabled(cls) -> RecordingStatus:
        return RecordingStatus(
            enabled=False,
            active=False,
            failed=False,
            overflow_policy=None,
            queue_maxsize=None,
            queue_size=0,
            queue_high_watermark=0,
            submitted_sets=0,
            written_sets=0,
            dropped_sets=0,
            queue_full_events=0,
            first_failure_at_set=None,
            last_error=None,
        )

    @classmethod
    def from_config(cls, config: RunConfig) -> "RecordingSink":
        if not config.recording.enabled:
            raise RecordingError("RecordingSink requires recording.enabled=true.")
        return cls(
            LeRobotRecorder(config),
            queue_maxsize=config.recording.queue_maxsize,
            overflow_policy=config.recording.overflow_policy,
        )

    def submit(self, aligned_set: AlignedFrameSet) -> bool:
        with self._lock:
            if self._failed:
                return False
            try:
                self._queue.put_nowait(aligned_set)
            except queue.Full:
                self._queue_full_events += 1
                self._dropped_sets += 1
                self._failed = True
                self._first_failure_at_set = aligned_set.set_id
                self._last_error = (
                    "recording queue full; marking recording failed while keeping stream alive "
                    f"(queue_maxsize={self._queue_maxsize})"
                )
                self._stop_event.set()
                return False
            self._queue_high_watermark = max(self._queue_high_watermark, self._queue.qsize())
            self._submitted_sets += 1
            return True

    def close(self) -> None:
        self._stop_event.set()
        self._worker.join(timeout=30)
        self._recorder.close()

    def status(self) -> RecordingStatus:
        with self._lock:
            return RecordingStatus(
                enabled=True,
                active=not self._stop_event.is_set() and not self._failed,
                failed=self._failed,
                overflow_policy=self._overflow_policy,
                queue_maxsize=self._queue_maxsize,
                queue_size=self._queue.qsize(),
                queue_high_watermark=self._queue_high_watermark,
                submitted_sets=self._submitted_sets,
                written_sets=self._written_sets,
                dropped_sets=self._dropped_sets,
                queue_full_events=self._queue_full_events,
                first_failure_at_set=self._first_failure_at_set,
                last_error=self._last_error,
            )

    def _mark_worker_failure(self, message: str) -> None:
        with self._lock:
            self._failed = True
            self._last_error = message
            self._stop_event.set()

    def _run_worker(self) -> None:
        while True:
            if self._stop_event.is_set() and self._queue.empty():
                return
            try:
                aligned_set = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._recorder.record(aligned_set)
                with self._lock:
                    self._written_sets += 1
            except Exception as exc:
                self._mark_worker_failure(f"recording worker failed: {exc}")
                return
            finally:
                self._queue.task_done()

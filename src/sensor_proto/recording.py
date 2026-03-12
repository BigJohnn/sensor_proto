from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
        )
        self._dataset = self._create_dataset()

    def record(self, aligned_set: AlignedFrameSet) -> None:
        dataset = self._require_dataset()
        payload: dict[str, Any] = {"task": self._config.recording.task}
        for camera in self._config.cameras:
            frame = aligned_set.frames.get(camera.id)
            if frame is None:
                raise RecordingError(f"Aligned frame set {aligned_set.set_id} is missing camera {camera.id}.")
            payload[self.session.camera_features[camera.id]] = self._frame_to_rgb_array(frame)
        dataset.add_frame(payload)
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

    def _create_dataset(self):
        dataset_class = self._load_dataset_class()
        create = dataset_class.create
        signature = inspect.signature(create)
        parameters = signature.parameters
        supports_var_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        )
        kwargs: dict[str, object] = {
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
        if supports_var_kwargs or "root" in parameters:
            kwargs["root"] = self.session.root_dir
        elif "root_dir" in parameters:
            kwargs["root_dir"] = self.session.root_dir
        return self._call_with_supported_kwargs(create, kwargs)

    def _require_dataset(self):
        if self._dataset is None:
            raise RecordingError("LeRobot dataset is not initialized.")
        return self._dataset

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
    def _load_numpy_module():
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - depends on runtime environment
            raise RecordingError("Recording LeRobot v3 datasets requires numpy in the runtime environment.") from exc
        return np

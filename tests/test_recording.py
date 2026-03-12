from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from sensor_proto.config import CameraConfig, RecordingConfig, RunConfig
from sensor_proto.models import AlignedFrameSet, Frame
from sensor_proto.recording import (
    LeRobotRecorder,
    RecordingError,
    build_camera_feature_map,
    resolve_recording_fps,
)


class FakeLeRobotDataset:
    last_instance = None

    @classmethod
    def create(cls, **kwargs):
        root = kwargs.get("root") or kwargs.get("root_dir")
        if root is not None and Path(root).exists():
            raise AssertionError("LeRobot dataset root should not exist before create().")
        instance = cls()
        instance.created_kwargs = kwargs
        instance.frames = []
        instance.saved_task = None
        instance.finalized = False
        cls.last_instance = instance
        return instance

    def add_frame(self, payload):
        self.frames.append(payload)

    def save_episode(self, task=None):
        self.saved_task = task

    def finalize(self):
        self.finalized = True


def build_run_config(root_dir: str, *, fps_a: int = 30, fps_b: int = 30) -> RunConfig:
    return RunConfig(
        duration_s=0.0,
        cameras=[
            CameraConfig(
                id="rs-00",
                kind="mock",
                model="realsense-d435i",
                fps=fps_a,
                width=1,
                height=1,
                capture_image_data=True,
            ),
            CameraConfig(
                id="rs 00",
                kind="mock",
                model="realsense-d455",
                fps=fps_b,
                width=1,
                height=1,
                capture_image_data=True,
            ),
        ],
        recording=RecordingConfig(
            enabled=True,
            root_dir=root_dir,
            repo_id="local/test-rig",
            task="collect-observations",
        ),
    )


def build_aligned_set() -> AlignedFrameSet:
    return AlignedFrameSet(
        set_id=7,
        reference_camera_id="rs-00",
        reference_timestamp_s=123.456,
        skew_ms=2.5,
        frames={
            "rs-00": Frame(
                camera_id="rs-00",
                camera_kind="mock",
                sequence=1,
                created_at=1.0,
                payload_size=3,
                width=1,
                height=1,
                pixel_format="bgr8",
                image_data=bytes([1, 2, 3]),
            ),
            "rs 00": Frame(
                camera_id="rs 00",
                camera_kind="mock",
                sequence=1,
                created_at=1.0,
                payload_size=3,
                width=1,
                height=1,
                pixel_format="bgr8",
                image_data=bytes([4, 5, 6]),
            ),
        },
        offsets_ms={"rs-00": 0.0, "rs 00": 2.5},
    )


class RecordingTests(unittest.TestCase):
    def test_build_camera_feature_map_sanitizes_and_deduplicates(self) -> None:
        feature_map = build_camera_feature_map(["rs-00", "rs 00", "00"])

        self.assertEqual(feature_map["rs-00"], "observation.images.rs_00")
        self.assertEqual(feature_map["rs 00"], "observation.images.rs_00_2")
        self.assertEqual(feature_map["00"], "observation.images.camera_00")

    def test_resolve_recording_fps_requires_explicit_override_for_mixed_fps(self) -> None:
        config = build_run_config("/tmp/unused", fps_a=30, fps_b=25)

        with self.assertRaises(RecordingError):
            resolve_recording_fps(config)

    def test_recorder_adds_aligned_frames_and_finalizes_episode(self) -> None:
        fake_module = types.SimpleNamespace(LeRobotDataset=FakeLeRobotDataset)

        def fake_import_module(name: str):
            if name == "lerobot.common.datasets.lerobot_dataset":
                return fake_module
            raise ImportError(name)

        with tempfile.TemporaryDirectory() as tmpdir:
            target_root = str(Path(tmpdir) / "dataset")
            config = build_run_config(target_root)
            with patch("sensor_proto.recording.importlib.import_module", side_effect=fake_import_module):
                recorder = LeRobotRecorder(config)
                recorder.record(build_aligned_set())
                recorder.close()

        dataset = FakeLeRobotDataset.last_instance
        self.assertIsNotNone(dataset)
        assert dataset is not None
        self.assertEqual(dataset.created_kwargs["repo_id"], "local/test-rig")
        self.assertEqual(dataset.created_kwargs["fps"], 30)
        self.assertEqual(dataset.created_kwargs["root"], Path(target_root).resolve())
        self.assertEqual(
            set(dataset.created_kwargs["features"]),
            {"observation.images.rs_00", "observation.images.rs_00_2"},
        )
        self.assertEqual(len(dataset.frames), 1)
        payload = dataset.frames[0]
        self.assertEqual(set(payload), {"task", "observation.images.rs_00", "observation.images.rs_00_2"})
        self.assertEqual(payload["task"], "collect-observations")
        self.assertEqual(payload["observation.images.rs_00"].shape, (1, 1, 3))
        self.assertEqual(payload["observation.images.rs_00"].tolist(), [[[3, 2, 1]]])
        self.assertEqual(payload["observation.images.rs_00_2"].tolist(), [[[6, 5, 4]]])
        self.assertEqual(dataset.saved_task, "collect-observations")
        self.assertTrue(dataset.finalized)


if __name__ == "__main__":
    unittest.main()

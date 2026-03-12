from __future__ import annotations

import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from sensor_proto.config import CameraConfig, RecordingConfig, RunConfig
from sensor_proto.models import AlignedFrameSet, Frame
from sensor_proto.recording import (
    LeRobotRecorder,
    RecordingSink,
    RecordingError,
    build_camera_feature_map,
    resolve_recording_fps,
)


class FakeLeRobotDataset:
    last_instance = None
    create_kwargs = None

    @classmethod
    def create(cls, **kwargs):
        root = kwargs.get("root") or kwargs.get("root_dir")
        if root is not None and Path(root).exists():
            raise AssertionError("LeRobot dataset root should not exist before create().")
        cls.create_kwargs = kwargs
        instance = cls(repo_id=kwargs["repo_id"], root=root)
        instance.created_kwargs = kwargs
        instance.frames = []
        instance.saved_task = None
        instance.finalized = False
        instance._streaming_encoder = None
        cls.last_instance = instance
        return instance

    def __init__(
        self,
        repo_id=None,
        root=None,
        streaming_encoding=False,
        vcodec=None,
        encoder_queue_maxsize=None,
        encoder_threads=None,
    ):
        self.repo_id = repo_id
        self.root = Path(root).resolve() if root is not None else None
        self.streaming_encoding = streaming_encoding
        self.vcodec = vcodec
        self.encoder_queue_maxsize = encoder_queue_maxsize
        self.encoder_threads = encoder_threads
        self.frames = []
        self.saved_task = None
        self.finalized = False
        type(self).last_instance = self

    def add_frame(self, payload):
        self.frames.append(payload)

    def save_episode(self, task=None):
        self.saved_task = task

    def finalize(self):
        self.finalized = True


class FakeStreamingVideoEncoder:
    last_instance = None

    def __init__(self, fps, vcodec="libsvtav1", queue_maxsize=30, encoder_threads=None):
        self.fps = fps
        self.vcodec = vcodec
        self.queue_maxsize = queue_maxsize
        self.encoder_threads = encoder_threads
        type(self).last_instance = self


class FakeRecorderBackend:
    def __init__(self) -> None:
        self.recorded: list[int] = []
        self.closed = False

    def record(self, aligned_set: AlignedFrameSet) -> None:
        self.recorded.append(aligned_set.set_id)

    def close(self) -> None:
        self.closed = True


class BlockingRecorderBackend(FakeRecorderBackend):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def record(self, aligned_set: AlignedFrameSet) -> None:
        self.started.set()
        self.release.wait(timeout=2.0)
        super().record(aligned_set)


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
        fake_dataset_module = types.SimpleNamespace(LeRobotDataset=FakeLeRobotDataset)
        fake_video_utils_module = types.SimpleNamespace(
            StreamingVideoEncoder=FakeStreamingVideoEncoder,
            resolve_vcodec=lambda codec: codec,
        )

        def fake_import_module(name: str):
            if name == "lerobot.common.datasets.lerobot_dataset":
                return fake_dataset_module
            if name == "lerobot.common.datasets.video_utils":
                return fake_video_utils_module
            raise ImportError(name)

        with tempfile.TemporaryDirectory() as tmpdir:
            target_root = str(Path(tmpdir) / "dataset")
            config = build_run_config(target_root)
            with patch("sensor_proto.recording.importlib.import_module", side_effect=fake_import_module):
                recorder = LeRobotRecorder(config)
                recorder.record(build_aligned_set())
                recorder.close()
            sidecar = json.loads((Path(target_root) / "meta" / "aligned_timestamps.json").read_text(encoding="utf-8"))

        dataset = FakeLeRobotDataset.last_instance
        self.assertIsNotNone(dataset)
        assert dataset is not None
        self.assertEqual(FakeLeRobotDataset.create_kwargs["repo_id"], "local/test-rig")
        self.assertEqual(FakeLeRobotDataset.create_kwargs["fps"], 30)
        self.assertEqual(FakeLeRobotDataset.create_kwargs["root"], Path(target_root).resolve())
        self.assertEqual(
            set(FakeLeRobotDataset.create_kwargs["features"]),
            {"observation.images.rs_00", "observation.images.rs_00_2"},
        )
        self.assertIsNotNone(dataset._streaming_encoder)
        self.assertIsInstance(dataset._streaming_encoder, FakeStreamingVideoEncoder)
        self.assertEqual(dataset.vcodec, "h264")
        self.assertEqual(dataset._streaming_encoder.queue_maxsize, 30)
        self.assertEqual(dataset._streaming_encoder.encoder_threads, None)
        self.assertEqual(len(dataset.frames), 1)
        payload = dataset.frames[0]
        self.assertEqual(set(payload), {"task", "observation.images.rs_00", "observation.images.rs_00_2"})
        self.assertEqual(payload["task"], "collect-observations")
        self.assertEqual(payload["observation.images.rs_00"].shape, (1, 1, 3))
        self.assertEqual(payload["observation.images.rs_00"].tolist(), [[[3, 2, 1]]])
        self.assertEqual(payload["observation.images.rs_00_2"].tolist(), [[[6, 5, 4]]])
        self.assertEqual(sidecar["timeline"], "aligned_reference_timestamp_s")
        self.assertEqual(sidecar["frame_count"], 1)
        self.assertEqual(sidecar["timestamps_s"], [0.0])
        self.assertEqual(dataset.saved_task, "collect-observations")
        self.assertTrue(dataset.finalized)

    def test_recording_sink_writes_frames_on_background_worker(self) -> None:
        backend = FakeRecorderBackend()
        sink = RecordingSink(backend, queue_maxsize=2, overflow_policy="fail_recording_keep_stream")

        accepted = sink.submit(build_aligned_set())
        sink.close()

        self.assertTrue(accepted)
        self.assertEqual(backend.recorded, [7])
        self.assertTrue(backend.closed)
        status = sink.status()
        self.assertEqual(status.submitted_sets, 1)
        self.assertEqual(status.written_sets, 1)
        self.assertFalse(status.failed)
        self.assertEqual(status.queue_high_watermark, 1)
        self.assertIsNone(status.first_failure_at_set)

    def test_recording_sink_fails_open_when_queue_fills(self) -> None:
        backend = BlockingRecorderBackend()
        sink = RecordingSink(backend, queue_maxsize=1, overflow_policy="fail_recording_keep_stream")

        self.assertTrue(sink.submit(build_aligned_set()))
        backend.started.wait(timeout=1.0)
        self.assertTrue(sink.submit(build_aligned_set()))
        self.assertFalse(sink.submit(build_aligned_set()))
        status = sink.status()
        self.assertTrue(status.failed)
        self.assertEqual(status.queue_full_events, 1)
        self.assertEqual(status.dropped_sets, 1)
        self.assertEqual(status.first_failure_at_set, 7)
        self.assertEqual(status.queue_high_watermark, 1)

        backend.release.set()
        sink.close()

        self.assertTrue(backend.closed)
        self.assertEqual(backend.recorded, [7, 7])


if __name__ == "__main__":
    unittest.main()

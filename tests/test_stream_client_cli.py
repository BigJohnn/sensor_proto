from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sensor_proto.stream_client import AlignedFrameBundle
from sensor_proto.stream_client_cli import build_summary, save_aligned_frames


class StreamClientCliTests(unittest.TestCase):
    def test_build_summary_includes_core_sync_fields(self) -> None:
        aligned = AlignedFrameBundle(
            set_id=7,
            timestamp=123.456,
            frames={"rs-00": object()},
            offsets_ms={"rs-00": 0.0},
            device_timestamps_ms={"rs-00": 1000.0},
            skew_ms=2.5,
            camera_order=["rs-00"],
            raw_payload={},
        )

        summary = build_summary(aligned, {"rs-00": "/tmp/frame.png"})

        self.assertEqual(summary["set_id"], 7)
        self.assertEqual(summary["timestamp"], 123.456)
        self.assertEqual(summary["skew_ms"], 2.5)
        self.assertEqual(summary["saved_files"], {"rs-00": "/tmp/frame.png"})

    def test_save_aligned_frames_writes_one_png_per_camera(self) -> None:
        aligned = AlignedFrameBundle(
            set_id=3,
            timestamp=1.0,
            frames={"rs-00": object(), "rs-01": object()},
            offsets_ms={"rs-00": 0.0, "rs-01": 1.0},
            device_timestamps_ms={"rs-00": 1000.0, "rs-01": 1001.0},
            skew_ms=1.0,
            camera_order=["rs-00", "rs-01"],
            raw_payload={},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_cv2 = type("FakeCv2", (), {"imwrite": staticmethod(lambda path, frame: True)})
            with patch("sensor_proto.stream_client_cli._load_cv2_module", return_value=fake_cv2):
                saved_files = save_aligned_frames(aligned, tmpdir)

        self.assertEqual(set(saved_files), {"rs-00", "rs-01"})
        self.assertTrue(saved_files["rs-00"].endswith("set-000003-rs-00.png"))
        self.assertTrue(Path(saved_files["rs-01"]).name.endswith("rs-01.png"))


if __name__ == "__main__":
    unittest.main()

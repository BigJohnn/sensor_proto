from __future__ import annotations

import unittest

from sensor_proto.config import CameraConfig, RunConfig, SyncConfig
from sensor_proto.pipeline import MultiCameraRunner


class MultiCameraRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_frames_from_multiple_cameras(self) -> None:
        config = RunConfig(
            duration_s=0.6,
            queue_size=32,
            processing_delay_ms=0.0,
            cameras=[
                CameraConfig(
                    id="cam-a",
                    kind="mock",
                    model="realsense-d435i",
                    fps=30,
                    width=640,
                    height=480,
                    max_frames=20,
                    seed=1,
                ),
                CameraConfig(
                    id="cam-b",
                    kind="mock",
                    model="orbbec-bolt",
                    fps=25,
                    width=640,
                    height=480,
                    max_frames=20,
                    seed=2,
                ),
            ],
        )

        report = await MultiCameraRunner(config).run()

        self.assertGreater(report.cameras["cam-a"].processed, 0)
        self.assertGreater(report.cameras["cam-b"].processed, 0)
        self.assertFalse(report.cameras["cam-a"].failed)
        self.assertFalse(report.cameras["cam-b"].failed)
        self.assertIsNotNone(report.sync)
        self.assertTrue(report.sync.enabled)
        self.assertGreater(report.sync.aligned_sets, 0)

    async def test_backpressure_records_drops(self) -> None:
        config = RunConfig(
            duration_s=0.8,
            queue_size=2,
            processing_delay_ms=40.0,
            cameras=[
                CameraConfig(
                    id="cam-a",
                    kind="mock",
                    model="realsense-d455",
                    fps=60,
                    width=640,
                    height=480,
                    max_frames=60,
                    seed=3,
                ),
                CameraConfig(
                    id="cam-b",
                    kind="mock",
                    model="orbbec-bolt",
                    fps=60,
                    width=640,
                    height=480,
                    max_frames=60,
                    seed=4,
                ),
            ],
        )

        report = await MultiCameraRunner(config).run()

        self.assertGreater(report.cameras["cam-a"].dropped + report.cameras["cam-b"].dropped, 0)
        self.assertIsNotNone(report.sync)

    async def test_camera_failure_isolated_from_other_streams(self) -> None:
        config = RunConfig(
            duration_s=0.8,
            queue_size=16,
            processing_delay_ms=0.0,
            cameras=[
                CameraConfig(
                    id="cam-fail",
                    kind="mock",
                    model="realsense-d435i",
                    fps=30,
                    width=640,
                    height=480,
                    mock_fail_after_frames=3,
                    seed=5,
                ),
                CameraConfig(
                    id="cam-ok",
                    kind="mock",
                    model="orbbec-bolt",
                    fps=30,
                    width=640,
                    height=480,
                    max_frames=20,
                    seed=6,
                ),
            ],
        )

        report = await MultiCameraRunner(config).run()

        self.assertTrue(report.cameras["cam-fail"].failed)
        self.assertGreater(report.cameras["cam-ok"].processed, 0)
        self.assertFalse(report.cameras["cam-ok"].failed)

    async def test_sync_metrics_track_soft_alignment_against_device_clock(self) -> None:
        config = RunConfig(
            duration_s=0.7,
            queue_size=16,
            processing_delay_ms=0.0,
            cameras=[
                CameraConfig(
                    id="cam-a",
                    kind="mock",
                    model="realsense-d435i",
                    fps=30,
                    width=640,
                    height=480,
                    max_frames=18,
                    mock_timestamp_offset_ms=3.0,
                    mock_sync_group="rig-a",
                    seed=21,
                ),
                CameraConfig(
                    id="cam-b",
                    kind="mock",
                    model="realsense-d455",
                    fps=30,
                    width=640,
                    height=480,
                    max_frames=18,
                    mock_timestamp_offset_ms=17.0,
                    mock_sync_group="rig-a",
                    seed=22,
                ),
            ],
        )

        report = await MultiCameraRunner(config).run()

        self.assertIsNotNone(report.sync)
        self.assertEqual(report.sync.hardware_sync_mode, "disabled")
        self.assertGreater(report.sync.aligned_sets, 0)
        self.assertEqual(report.sync.dropped_frames, 0)
        self.assertLessEqual(report.sync.max_skew_ms, report.sync.tolerance_ms)
        self.assertIn("cam-a", report.sync.per_camera)
        self.assertIn("cam-b", report.sync.per_camera)
        self.assertEqual(report.sync.per_camera["cam-a"].dropped_frames, 0)
        self.assertIsNotNone(report.sync.per_camera["cam-b"].first_offset_ms)

    async def test_sync_metrics_drop_out_of_window_frames(self) -> None:
        config = RunConfig(
            duration_s=0.8,
            queue_size=16,
            processing_delay_ms=0.0,
            sync=SyncConfig(
                enabled=True,
                strategy="device-clock-soft-sync",
                tolerance_ms=2.0,
                max_buffered_frames=2,
                hardware_sync_mode="disabled",
            ),
            cameras=[
                CameraConfig(
                    id="cam-a",
                    kind="mock",
                    model="realsense-d435i",
                    fps=30,
                    width=640,
                    height=480,
                    max_frames=18,
                    seed=31,
                ),
                CameraConfig(
                    id="cam-b",
                    kind="mock",
                    model="realsense-d455",
                    fps=15,
                    width=640,
                    height=480,
                    max_frames=10,
                    seed=32,
                ),
            ],
        )

        report = await MultiCameraRunner(config).run()

        self.assertIsNotNone(report.sync)
        self.assertGreater(report.sync.incomplete_sets, 0)
        self.assertGreater(report.sync.dropped_frames, 0)
        self.assertGreater(len(report.sync.warnings), 0)

    async def test_sync_metrics_report_offset_drift_and_health_warnings(self) -> None:
        config = RunConfig(
            duration_s=1.2,
            queue_size=32,
            processing_delay_ms=0.0,
            sync=SyncConfig(
                enabled=True,
                strategy="device-clock-soft-sync",
                tolerance_ms=8.0,
                max_buffered_frames=4,
                reference_camera_id="cam-ref",
                hardware_sync_mode="disabled",
            ),
            cameras=[
                CameraConfig(
                    id="cam-ref",
                    kind="mock",
                    model="realsense-d435i",
                    fps=30,
                    width=640,
                    height=480,
                    max_frames=36,
                    seed=41,
                ),
                CameraConfig(
                    id="cam-drift",
                    kind="mock",
                    model="realsense-d455",
                    fps=30,
                    width=640,
                    height=480,
                    max_frames=36,
                    mock_timestamp_offset_ms=5.0,
                    mock_timestamp_drift_ppm=5000.0,
                    seed=42,
                ),
            ],
        )

        report = await MultiCameraRunner(config).run()

        self.assertIsNotNone(report.sync)
        drift_metrics = report.sync.per_camera["cam-drift"].as_dict()
        self.assertNotEqual(drift_metrics["avg_offset_ms"], 0.0)
        self.assertNotEqual(drift_metrics["drift_ppm"], 0.0)
        self.assertTrue(any(w.code == "clock_drift" for w in report.sync.warnings))


if __name__ == "__main__":
    unittest.main()

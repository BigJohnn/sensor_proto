from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from sensor_proto.cameras.realsense import RealSenseCameraAdapter
from sensor_proto.config import CameraConfig


async def _run_inline(func, *args, **kwargs):
    return func(*args, **kwargs)


class _FakeRSConfig:
    def enable_device(self, serial: str) -> None:
        self.serial = serial

    def enable_stream(self, *args) -> None:
        self.stream_args = args


class _FakeRSPipeline:
    def start(self, config) -> None:
        self.started_with = config

    def stop(self) -> None:
        self.stopped = True


class _FakeRSModule:
    class stream:
        color = "color"

    class format:
        bgr8 = "bgr8"

    def pipeline(self):
        return _FakeRSPipeline()

    def config(self):
        return _FakeRSConfig()


def _make_camera_config() -> CameraConfig:
    return CameraConfig(
        id="rs-05",
        kind="realsense",
        model="D435I",
        fps=30,
        width=640,
        height=480,
        serial="123456789",
        capture_image_data=True,
    )


class RealSenseRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recoverable_timeout_increments_failure_count_without_restart(self) -> None:
        adapter = RealSenseCameraAdapter(_make_camera_config(), rs_module=_FakeRSModule())
        adapter._start = Mock()
        adapter._next_frame = Mock(side_effect=RuntimeError("Frame didn't arrive within 5000"))
        adapter._restart_pipeline = Mock()

        with (
            patch("sensor_proto.cameras.realsense.asyncio.sleep", new=AsyncMock()) as sleep_mock,
            patch("sensor_proto.cameras.realsense.asyncio.to_thread", side_effect=_run_inline),
        ):
            frame_data, failure_count = await adapter._next_frame_with_recovery(0)

        self.assertIsNone(frame_data)
        self.assertEqual(failure_count, 1)
        adapter._restart_pipeline.assert_not_called()
        sleep_mock.assert_awaited_once()

    async def test_persistent_timeouts_restart_pipeline_and_reset_failure_count(self) -> None:
        adapter = RealSenseCameraAdapter(_make_camera_config(), rs_module=_FakeRSModule())
        adapter._start = Mock()
        adapter._next_frame = Mock(side_effect=RuntimeError("Frame didn't arrive within 5000"))
        adapter._restart_pipeline = Mock()

        with (
            patch("sensor_proto.cameras.realsense.asyncio.sleep", new=AsyncMock()) as sleep_mock,
            patch("sensor_proto.cameras.realsense.asyncio.to_thread", side_effect=_run_inline),
        ):
            frame_data, failure_count = await adapter._next_frame_with_recovery(adapter._restart_after_failures - 1)

        self.assertIsNone(frame_data)
        self.assertEqual(failure_count, 0)
        adapter._restart_pipeline.assert_called_once_with()
        sleep_mock.assert_awaited_once()

    async def test_non_recoverable_error_propagates(self) -> None:
        adapter = RealSenseCameraAdapter(_make_camera_config(), rs_module=_FakeRSModule())
        adapter._start = Mock()
        adapter._next_frame = Mock(side_effect=RuntimeError("device permission denied"))

        with (
            patch("sensor_proto.cameras.realsense.asyncio.to_thread", side_effect=_run_inline),
            self.assertRaisesRegex(RuntimeError, "permission denied"),
        ):
            await adapter._next_frame_with_recovery(0)


if __name__ == "__main__":
    unittest.main()

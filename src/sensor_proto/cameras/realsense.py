from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from sensor_proto.cameras.base import CameraAdapter
from sensor_proto.models import Frame


class RealSenseCameraAdapter(CameraAdapter):
    _frame_timeout_ms = 5000
    _frame_retry_backoff_s = 0.1
    _restart_retry_backoff_s = 0.5
    _restart_after_failures = 3

    def __init__(self, config, rs_module=None) -> None:
        super().__init__(config)
        if rs_module is None:
            try:
                import pyrealsense2 as rs_module
            except ImportError as exc:
                raise RuntimeError("pyrealsense2 is not installed in this environment.") from exc

        self._rs = rs_module
        self._pipeline = self._create_pipeline()
        self._started = False

    def _create_pipeline(self):
        return self._rs.pipeline()

    def _build_rs_config(self):
        config = self._rs.config()
        if self.config.serial:
            config.enable_device(self.config.serial)
        config.enable_stream(
            self._rs.stream.color,
            self.config.width,
            self.config.height,
            self._rs.format.bgr8,
            self.config.fps,
        )
        return config

    def _start(self) -> None:
        if self._started:
            return
        self._pipeline.start(self._build_rs_config())
        self._started = True

    def _stop_pipeline(self) -> None:
        if not self._started:
            return
        try:
            self._pipeline.stop()
        except RuntimeError:
            pass
        self._started = False

    def _restart_pipeline(self) -> None:
        self._stop_pipeline()
        self._pipeline = self._create_pipeline()
        self._start()

    def _next_frame(self) -> dict[str, object]:
        frames = self._pipeline.wait_for_frames(self._frame_timeout_ms)
        color = frames.get_color_frame()
        if not color:
            raise RuntimeError(f"{self.config.id} did not return a color frame.")
        if hasattr(color, "get_data_size"):
            payload_size = int(color.get_data_size())
        else:
            payload_size = len(bytes(color.get_data()))
        device_timestamp_ms = float(color.get_timestamp()) if hasattr(color, "get_timestamp") else None
        frame_counter = int(color.get_frame_number()) if hasattr(color, "get_frame_number") else None
        timestamp_domain = None
        if hasattr(color, "get_frame_timestamp_domain"):
            timestamp_domain = str(color.get_frame_timestamp_domain())
        return {
            "payload_size": payload_size,
            "device_timestamp_ms": device_timestamp_ms,
            "frame_counter": frame_counter,
            "timestamp_domain": timestamp_domain,
            "image_data": bytes(color.get_data()) if self.config.capture_image_data else None,
        }

    def _is_recoverable_frame_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "didn't arrive within" in message
            or "frame didn't arrive" in message
            or "timeout" in message
            or "did not return a color frame" in message
        )

    async def _next_frame_with_recovery(self, consecutive_failures: int) -> tuple[dict[str, object] | None, int]:
        self._start()
        try:
            frame_data = await asyncio.to_thread(self._next_frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._is_recoverable_frame_error(exc):
                raise
            consecutive_failures += 1
            if consecutive_failures >= self._restart_after_failures:
                print(
                    f"{self.config.id}: frame retrieval stalled after {consecutive_failures} recoverable errors; restarting pipeline.",
                    flush=True,
                )
                try:
                    await asyncio.to_thread(self._restart_pipeline)
                except Exception as restart_exc:
                    print(f"{self.config.id}: pipeline restart failed: {restart_exc}", flush=True)
                    await asyncio.sleep(self._restart_retry_backoff_s)
                    return None, consecutive_failures
                await asyncio.sleep(self._restart_retry_backoff_s)
                return None, 0
            await asyncio.sleep(self._frame_retry_backoff_s)
            return None, consecutive_failures
        return frame_data, 0

    async def frames(self) -> AsyncIterator[Frame]:
        sequence = 0
        consecutive_failures = 0
        try:
            while True:
                frame_data, consecutive_failures = await self._next_frame_with_recovery(consecutive_failures)
                if frame_data is None:
                    continue
                host_received_at = time.monotonic()
                yield Frame(
                    camera_id=self.config.id,
                    camera_kind=self.config.kind,
                    sequence=sequence,
                    created_at=host_received_at,
                    payload_size=int(frame_data["payload_size"]),
                    host_received_at=host_received_at,
                    device_timestamp_ms=(
                        float(frame_data["device_timestamp_ms"])
                        if frame_data["device_timestamp_ms"] is not None
                        else None
                    ),
                    timestamp_domain=(
                        str(frame_data["timestamp_domain"])
                        if frame_data["timestamp_domain"] is not None
                        else None
                    ),
                    frame_counter=(
                        int(frame_data["frame_counter"])
                        if frame_data["frame_counter"] is not None
                        else None
                    ),
                    sensor_serial=self.config.serial,
                    width=self.config.width,
                    height=self.config.height,
                    pixel_format="bgr8" if self.config.capture_image_data else None,
                    image_data=frame_data["image_data"] if frame_data["image_data"] is not None else None,
                )
                sequence += 1
        finally:
            await self.close()

    async def close(self) -> None:
        await asyncio.to_thread(self._stop_pipeline)

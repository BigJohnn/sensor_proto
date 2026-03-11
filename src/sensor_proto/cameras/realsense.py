from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from sensor_proto.cameras.base import CameraAdapter
from sensor_proto.models import Frame


class RealSenseCameraAdapter(CameraAdapter):
    def __init__(self, config) -> None:
        super().__init__(config)
        try:
            import pyrealsense2 as rs
        except ImportError as exc:
            raise RuntimeError("pyrealsense2 is not installed in this environment.") from exc

        self._rs = rs
        self._pipeline = rs.pipeline()
        self._started = False

    def _start(self) -> None:
        if self._started:
            return
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
        self._pipeline.start(config)
        self._started = True

    def _next_frame(self) -> dict[str, object]:
        frames = self._pipeline.wait_for_frames(5000)
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
        }

    async def frames(self) -> AsyncIterator[Frame]:
        self._start()
        sequence = 0
        try:
            while True:
                frame_data = await asyncio.to_thread(self._next_frame)
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
                )
                sequence += 1
        finally:
            await self.close()

    async def close(self) -> None:
        if self._started:
            await asyncio.to_thread(self._pipeline.stop)
            self._started = False

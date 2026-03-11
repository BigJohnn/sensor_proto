from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from sensor_proto.cameras.base import CameraAdapter
from sensor_proto.models import Frame


class OrbbecCameraAdapter(CameraAdapter):
    def __init__(self, config) -> None:
        super().__init__(config)
        try:
            from pyorbbecsdk import Config, Context, OBFormat, OBSensorType, Pipeline
        except ImportError as exc:
            raise RuntimeError("pyorbbecsdk is not installed in this environment.") from exc

        self._Config = Config
        self._Context = Context
        self._OBFormat = OBFormat
        self._OBSensorType = OBSensorType
        self._Pipeline = Pipeline
        self._pipeline = None
        self._started = False

    def _build_pipeline(self):
        ctx = self._Context()
        devices = ctx.query_devices()
        if devices.get_count() == 0:
            raise RuntimeError("No Orbbec devices found.")
        if self.config.serial:
            for index in range(devices.get_count()):
                device = devices.get_device_by_index(index)
                if device.get_device_info().get_serial_number() == self.config.serial:
                    return self._Pipeline(device)
            raise RuntimeError(f"Orbbec device {self.config.serial} not found.")
        return self._Pipeline()

    def _start(self) -> None:
        if self._started:
            return
        self._pipeline = self._build_pipeline()
        config = self._Config()
        profiles = self._pipeline.get_stream_profile_list(self._OBSensorType.COLOR_SENSOR)
        profile = profiles.get_video_stream_profile(
            self.config.width,
            self.config.height,
            self._OBFormat.RGB,
            self.config.fps,
        )
        config.enable_stream(profile)
        self._pipeline.start(config)
        self._started = True

    def _next_frame(self) -> dict[str, object]:
        frames = self._pipeline.wait_for_frames(5000)
        color = frames.get_color_frame()
        if color is None:
            raise RuntimeError(f"{self.config.id} did not return a color frame.")
        if hasattr(color, "get_data_size"):
            payload_size = int(color.get_data_size())
        else:
            payload_size = len(bytes(color.get_data()))
        device_timestamp_ms = None
        for attr in ("get_timestamp", "timestamp"):
            if hasattr(color, attr):
                value = getattr(color, attr)
                device_timestamp_ms = float(value() if callable(value) else value)
                break
        frame_counter = None
        for attr in ("get_index", "get_frame_index", "get_frame_number"):
            if hasattr(color, attr):
                value = getattr(color, attr)
                frame_counter = int(value() if callable(value) else value)
                break
        return {
            "payload_size": payload_size,
            "device_timestamp_ms": device_timestamp_ms,
            "frame_counter": frame_counter,
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
                    timestamp_domain="orbbec-device-clock",
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
        if self._started and self._pipeline is not None:
            await asyncio.to_thread(self._pipeline.stop)
            self._started = False

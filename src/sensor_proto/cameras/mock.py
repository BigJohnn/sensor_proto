from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator

from sensor_proto.cameras.base import CameraAdapter
from sensor_proto.models import Frame


class MockCameraAdapter(CameraAdapter):
    def _build_image_data(self, sequence: int) -> bytes | None:
        if not self.config.capture_image_data:
            return None
        pixel_count = self.config.width * self.config.height
        blue = sequence % 256
        green = (self.config.seed * 17) % 256
        red = (sequence * 3 + self.config.seed) % 256
        return bytes((blue, green, red)) * pixel_count

    async def frames(self) -> AsyncIterator[Frame]:
        interval_s = 1.0 / max(self.config.fps, 1)
        jitter_s = max(self.config.mock_jitter_ms, 0.0) / 1000.0
        payload_size = self.config.mock_payload_size or self.config.width * self.config.height * 3
        rng = random.Random(self.config.seed)
        device_clock_origin_ms = self.config.mock_timestamp_offset_ms
        drift_scale = 1.0 + (self.config.mock_timestamp_drift_ppm / 1_000_000.0)
        sequence = 0

        while True:
            if self.config.max_frames is not None and sequence >= self.config.max_frames:
                return
            if self.config.mock_fail_after_frames is not None and sequence >= self.config.mock_fail_after_frames:
                raise RuntimeError(f"{self.config.id} simulated failure after {sequence} frames")

            await asyncio.sleep(interval_s + rng.uniform(0.0, jitter_s))
            host_received_at = time.monotonic()
            device_timestamp_ms = device_clock_origin_ms + (sequence * interval_s * 1000.0 * drift_scale)
            yield Frame(
                camera_id=self.config.id,
                camera_kind=self.config.kind,
                sequence=sequence,
                created_at=host_received_at,
                payload_size=payload_size,
                host_received_at=host_received_at,
                device_timestamp_ms=device_timestamp_ms,
                timestamp_domain="mock-device-clock",
                frame_counter=sequence,
                sensor_serial=self.config.serial or f"mock-{self.config.id}",
                hardware_sync_group=self.config.mock_sync_group,
                width=self.config.width,
                height=self.config.height,
                pixel_format="bgr8" if self.config.capture_image_data else None,
                image_data=self._build_image_data(sequence),
            )
            sequence += 1

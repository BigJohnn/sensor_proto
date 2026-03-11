from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from sensor_proto.cameras import create_camera_adapter
from sensor_proto.config import RunConfig
from sensor_proto.models import AlignedFrameSet, CameraMetrics, Frame
from sensor_proto.synchronization import FrameSynchronizer


AlignedSetCallback = Callable[[AlignedFrameSet, dict[str, object], dict[str, object]], None]
ErrorCallback = Callable[[str], None]


class SynchronizedStreamRunner:
    def __init__(
        self,
        config: RunConfig,
        on_aligned_set: AlignedSetCallback,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.config = config
        self._on_aligned_set = on_aligned_set
        self._on_error = on_error

    async def run_until_stopped(self, stop_requested) -> None:
        synchronizer = FrameSynchronizer(self.config)
        camera_metrics = {camera.id: CameraMetrics() for camera in self.config.cameras}
        queue: asyncio.Queue[Frame] = asyncio.Queue(maxsize=self.config.queue_size)
        stop_event = asyncio.Event()
        adapters = []

        async def producer(camera_config) -> None:
            adapter = create_camera_adapter(camera_config)
            adapters.append(adapter)
            metrics = camera_metrics[camera_config.id]
            try:
                async for frame in adapter.frames():
                    if stop_event.is_set():
                        break
                    metrics.produced += 1
                    try:
                        queue.put_nowait(frame)
                    except asyncio.QueueFull:
                        metrics.dropped += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                metrics.failed = True
                metrics.failure_reason = str(exc)
                if self._on_error is not None:
                    self._on_error(f"{camera_config.id}: {exc}")
            finally:
                await adapter.close()

        async def consumer() -> None:
            while True:
                frame = await queue.get()
                try:
                    aligned_sets = synchronizer.observe(frame)
                    latency_ms = (time.monotonic() - (frame.host_received_at or frame.created_at)) * 1000.0
                    metrics = camera_metrics[frame.camera_id]
                    metrics.processed += 1
                    metrics.record_latency(latency_ms)
                    for aligned_set in aligned_sets:
                        self._on_aligned_set(
                            aligned_set,
                            synchronizer.metrics.as_dict(),
                            {camera_id: metric.as_dict() for camera_id, metric in camera_metrics.items()},
                        )
                finally:
                    queue.task_done()

        producer_tasks = [asyncio.create_task(producer(camera)) for camera in self.config.cameras]
        consumer_task = asyncio.create_task(consumer())

        try:
            await asyncio.to_thread(stop_requested.wait)
        finally:
            stop_event.set()
            for task in producer_tasks:
                task.cancel()
            await asyncio.gather(*producer_tasks, return_exceptions=True)
            await queue.join()
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)
            for adapter in adapters:
                await adapter.close()

from __future__ import annotations

import asyncio
import time

from sensor_proto.cameras import create_camera_adapter
from sensor_proto.config import RunConfig
from sensor_proto.models import CameraMetrics, Frame, RunReport
from sensor_proto.synchronization import FrameSynchronizer


class MultiCameraRunner:
    def __init__(self, config: RunConfig) -> None:
        self.config = config

    async def run(self) -> RunReport:
        synchronizer = FrameSynchronizer(self.config)
        report = RunReport(
            duration_s=self.config.duration_s,
            queue_size=self.config.queue_size,
            processing_delay_ms=self.config.processing_delay_ms,
            cameras={camera.id: CameraMetrics() for camera in self.config.cameras},
            sync=synchronizer.metrics,
        )
        queue: asyncio.Queue[Frame] = asyncio.Queue(maxsize=self.config.queue_size)
        stop_event = asyncio.Event()
        adapters = []

        async def producer(camera_config) -> None:
            adapter = create_camera_adapter(camera_config)
            adapters.append(adapter)
            metrics = report.cameras[camera_config.id]
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
            finally:
                await adapter.close()

        async def consumer() -> None:
            while True:
                frame = await queue.get()
                try:
                    if self.config.processing_delay_ms > 0:
                        await asyncio.sleep(self.config.processing_delay_ms / 1000.0)
                    synchronizer.observe(frame)
                    latency_ms = (time.monotonic() - (frame.host_received_at or frame.created_at)) * 1000.0
                    metrics = report.cameras[frame.camera_id]
                    metrics.processed += 1
                    metrics.record_latency(latency_ms)
                finally:
                    queue.task_done()

        producer_tasks = [asyncio.create_task(producer(camera)) for camera in self.config.cameras]
        consumer_task = asyncio.create_task(consumer())

        try:
            await asyncio.sleep(self.config.duration_s)
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
            report.sync = synchronizer.finalize()

        return report

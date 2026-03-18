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
    # How long without a new aligned set before declaring a stall.
    _stall_timeout_s: float = 15.0
    # How often the watchdog wakes to check (detection latency ≤ timeout + interval).
    _stall_check_interval_s: float = 5.0
    # Pause between stall detection and camera re-open (lets USB release cleanly).
    _stall_restart_delay_s: float = 1.0

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
        # Shared mutable timestamp — updated by consumer on every aligned set.
        last_aligned_at: list[float] = [time.monotonic()]
        restart_count = 0

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
                        last_aligned_at[0] = time.monotonic()
                        self._on_aligned_set(
                            aligned_set,
                            synchronizer.metrics.as_dict(),
                            {camera_id: metric.as_dict() for camera_id, metric in camera_metrics.items()},
                        )
                finally:
                    queue.task_done()

        consumer_task = asyncio.create_task(consumer())

        try:
            while not stop_event.is_set():
                if restart_count > 0:
                    await asyncio.sleep(self._stall_restart_delay_s)
                    synchronizer.reset()
                    last_aligned_at[0] = time.monotonic()
                    print(f"Camera session restarted (stall recovery #{restart_count}).", flush=True)

                # Per-session state: a new restart_event and adapters list each time.
                restart_event = asyncio.Event()
                adapters: list = []

                async def producer(camera_config, _re=restart_event) -> None:
                    adapter = create_camera_adapter(camera_config)
                    adapters.append(adapter)
                    metrics = camera_metrics[camera_config.id]
                    try:
                        async for frame in adapter.frames():
                            if stop_event.is_set() or _re.is_set():
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

                async def watchdog(_re=restart_event, _last=last_aligned_at) -> None:
                    while not stop_event.is_set() and not _re.is_set():
                        await asyncio.sleep(self._stall_check_interval_s)
                        if stop_event.is_set() or _re.is_set():
                            break
                        elapsed = time.monotonic() - _last[0]
                        if elapsed >= self._stall_timeout_s:
                            print(
                                f"Stream stall detected: no aligned sets for {elapsed:.1f}s, "
                                "restarting cameras.",
                                flush=True,
                            )
                            _re.set()

                producer_tasks = [
                    asyncio.create_task(producer(camera)) for camera in self.config.cameras
                ]
                watchdog_task = asyncio.create_task(watchdog())

                # Poll until stop or stall restart is signalled.
                while not stop_requested.is_set() and not stop_event.is_set() and not restart_event.is_set():
                    await asyncio.sleep(0.25)

                if stop_requested.is_set():
                    stop_event.set()

                # Tear down the current session.
                restart_event.set()
                watchdog_task.cancel()
                for task in producer_tasks:
                    task.cancel()
                await asyncio.gather(watchdog_task, *producer_tasks, return_exceptions=True)
                for adapter in adapters:
                    await adapter.close()

                if not stop_event.is_set():
                    restart_count += 1

        finally:
            stop_event.set()
            await queue.join()
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable

from sensor_proto.transport.sinks import AlignedSetEvent
from sensor_proto.transport.zmq.publisher import ZmqAlignedSetPublisher, ZmqPublishWouldBlock


@dataclass(slots=True)
class ZmqTransportStatus:
    enabled: bool
    active: bool
    failed: bool
    backpressure_strategy: str
    queue_maxsize: int
    queue_size: int
    submitted_sets: int
    published_sets: int
    dropped_sets: int
    would_block_events: int
    last_error: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "active": self.active,
            "failed": self.failed,
            "backpressure_strategy": self.backpressure_strategy,
            "queue_maxsize": self.queue_maxsize,
            "queue_size": self.queue_size,
            "submitted_sets": self.submitted_sets,
            "published_sets": self.published_sets,
            "dropped_sets": self.dropped_sets,
            "would_block_events": self.would_block_events,
            "last_error": self.last_error,
        }


class ZmqAlignedSetSink:
    def __init__(
        self,
        publisher: ZmqAlignedSetPublisher,
        camera_order: list[str],
        *,
        max_queue: int = 1,
        backpressure_strategy: str = "latest_only_drop_oldest",
        on_error: Callable[[str], None] | None = None,
        on_status: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        if backpressure_strategy != "latest_only_drop_oldest":
            raise ValueError(f"Unsupported ZMQ backpressure strategy: {backpressure_strategy}")
        self._publisher = publisher
        self._camera_order = list(camera_order)
        self._max_queue = max(int(max_queue), 1)
        self._backpressure_strategy = backpressure_strategy
        self._on_error = on_error
        self._on_status = on_status
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._queue: deque[AlignedSetEvent] = deque()
        self._stop_requested = False
        self._failed = False
        self._submitted_sets = 0
        self._published_sets = 0
        self._dropped_sets = 0
        self._would_block_events = 0
        self._last_error: str | None = None
        self._publisher.open()
        self._worker = threading.Thread(target=self._run_worker, name="zmq-aligned-set-publisher", daemon=True)
        self._worker.start()
        self._emit_status()

    def publish(self, event: AlignedSetEvent) -> None:
        with self._condition:
            if self._failed or self._stop_requested:
                return
            if len(self._queue) >= self._max_queue:
                self._queue.popleft()
                self._dropped_sets += 1
            self._queue.append(event)
            self._submitted_sets += 1
            self._condition.notify()
        self._emit_status()

    def close(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
        self._worker.join(timeout=10)
        self._publisher.close()
        self._emit_status()

    def status(self) -> ZmqTransportStatus:
        with self._lock:
            return ZmqTransportStatus(
                enabled=True,
                active=not self._stop_requested and not self._failed,
                failed=self._failed,
                backpressure_strategy=self._backpressure_strategy,
                queue_maxsize=self._max_queue,
                queue_size=len(self._queue),
                submitted_sets=self._submitted_sets,
                published_sets=self._published_sets,
                dropped_sets=self._dropped_sets,
                would_block_events=self._would_block_events,
                last_error=self._last_error,
            )

    def _emit_status(self) -> None:
        if self._on_status is not None:
            self._on_status(self.status().as_dict())

    def _run_worker(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._stop_requested:
                    self._condition.wait()
                if self._stop_requested and not self._queue:
                    return
                event = self._queue.popleft()
            try:
                self._publisher.publish(event.aligned_set, self._camera_order)
            except ZmqPublishWouldBlock:
                with self._lock:
                    self._would_block_events += 1
                    self._dropped_sets += 1
                self._emit_status()
                continue
            except Exception as exc:
                message = str(exc)
                with self._condition:
                    self._failed = True
                    self._last_error = message
                    self._stop_requested = True
                    self._condition.notify_all()
                self._emit_status()
                if self._on_error is not None:
                    self._on_error(f"ZMQ transport failed: {message}")
                return
            with self._lock:
                self._published_sets += 1
            self._emit_status()

from __future__ import annotations

import threading
import time
import unittest

from sensor_proto.models import AlignedFrameSet
from sensor_proto.transport.sinks import AlignedSetEvent
from sensor_proto.transport.zmq.publisher import ZmqPublishWouldBlock
from sensor_proto.transport.zmq.sink import ZmqAlignedSetSink


class _BlockingPublisher:
    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self.opened = 0
        self.closed = 0
        self.published_set_ids: list[int] = []

    def open(self) -> None:
        self.opened += 1

    def close(self) -> None:
        self.closed += 1

    def publish(self, aligned_set: AlignedFrameSet, camera_order: list[str]) -> None:
        self.published_set_ids.append(aligned_set.set_id)
        self._gate.wait(timeout=1.0)


class _WouldBlockPublisher:
    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0

    def open(self) -> None:
        self.opened += 1

    def close(self) -> None:
        self.closed += 1

    def publish(self, aligned_set: AlignedFrameSet, camera_order: list[str]) -> None:
        raise ZmqPublishWouldBlock("would block")


def _event(set_id: int) -> AlignedSetEvent:
    return AlignedSetEvent(
        aligned_set=AlignedFrameSet(
            set_id=set_id,
            reference_camera_id="cam-a",
            reference_timestamp_s=float(set_id),
            skew_ms=0.0,
        ),
        sync_snapshot={},
        camera_snapshot={},
    )


class ZmqSinkTests(unittest.TestCase):
    def test_sink_reports_status_via_callback(self) -> None:
        statuses: list[dict[str, object]] = []
        publisher = _WouldBlockPublisher()
        sink = ZmqAlignedSetSink(
            publisher,
            camera_order=["cam-a"],
            max_queue=1,
            backpressure_strategy="latest_only_drop_oldest",
            on_status=statuses.append,
        )
        try:
            sink.publish(_event(1))
            time.sleep(0.05)
        finally:
            sink.close()

        self.assertTrue(statuses)
        self.assertTrue(any(status["enabled"] for status in statuses))
        self.assertTrue(any(status["would_block_events"] == 1 for status in statuses))

    def test_latest_only_drop_oldest_drops_whole_aligned_sets(self) -> None:
        gate = threading.Event()
        publisher = _BlockingPublisher(gate)
        sink = ZmqAlignedSetSink(
            publisher,
            camera_order=["cam-a"],
            max_queue=1,
            backpressure_strategy="latest_only_drop_oldest",
        )
        try:
            sink.publish(_event(1))
            time.sleep(0.01)
            sink.publish(_event(2))
            sink.publish(_event(3))
            gate.set()
            time.sleep(0.05)
            status = sink.status()
        finally:
            sink.close()

        self.assertEqual(publisher.opened, 1)
        self.assertIn(1, publisher.published_set_ids)
        self.assertIn(3, publisher.published_set_ids)
        self.assertNotIn(2, publisher.published_set_ids)
        self.assertEqual(status.dropped_sets, 1)
        self.assertEqual(status.backpressure_strategy, "latest_only_drop_oldest")

    def test_would_block_counts_as_whole_set_drop(self) -> None:
        publisher = _WouldBlockPublisher()
        sink = ZmqAlignedSetSink(
            publisher,
            camera_order=["cam-a"],
            max_queue=1,
            backpressure_strategy="latest_only_drop_oldest",
        )
        try:
            sink.publish(_event(5))
            time.sleep(0.05)
            status = sink.status()
        finally:
            sink.close()

        self.assertEqual(status.published_sets, 0)
        self.assertEqual(status.dropped_sets, 1)
        self.assertEqual(status.would_block_events, 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from sensor_proto.models import AlignedFrameSet
from sensor_proto.recording import RecordingStatus
from sensor_proto.transport.sinks import AlignedSetEvent, CompositeAlignedSetSink, RecordingAlignedSetSink, RepositoryAlignedSetSink


class _FakeRepository:
    def __init__(self) -> None:
        self.published: list[tuple[AlignedFrameSet, dict[str, object], dict[str, object]]] = []
        self.recording_status_payloads: list[dict[str, object]] = []

    def publish(
        self,
        aligned_set: AlignedFrameSet,
        sync_snapshot: dict[str, object],
        camera_snapshot: dict[str, object],
    ) -> None:
        self.published.append((aligned_set, sync_snapshot, camera_snapshot))

    def set_recording_status(self, payload: dict[str, object]) -> None:
        self.recording_status_payloads.append(payload)


class _FakeRecordingSink:
    def __init__(self, accepted: bool, status: RecordingStatus) -> None:
        self._accepted = accepted
        self._status = status
        self.submitted_set_ids: list[int] = []

    def submit(self, aligned_set: AlignedFrameSet) -> bool:
        self.submitted_set_ids.append(aligned_set.set_id)
        return self._accepted

    def status(self) -> RecordingStatus:
        return self._status


class TransportSinkTests(unittest.TestCase):
    def test_recording_sink_reports_initial_and_latest_status_to_repository(self) -> None:
        repository = _FakeRepository()
        status = RecordingStatus(
            enabled=True,
            active=True,
            failed=False,
            overflow_policy="fail_recording_keep_stream",
            queue_maxsize=8,
            queue_size=1,
            queue_high_watermark=3,
            submitted_sets=5,
            written_sets=4,
            dropped_sets=0,
            queue_full_events=0,
            first_failure_at_set=None,
            last_error=None,
        )
        recording_sink = _FakeRecordingSink(accepted=True, status=status)

        sink = RecordingAlignedSetSink(repository, recording_sink)
        event = AlignedSetEvent(
            aligned_set=AlignedFrameSet(
                set_id=12,
                reference_camera_id="cam-a",
                reference_timestamp_s=1.25,
                skew_ms=0.5,
            ),
            sync_snapshot={"aligned_sets": 9},
            camera_snapshot={"cam-a": {"processed": 9}},
        )

        sink.publish(event)

        self.assertEqual(recording_sink.submitted_set_ids, [12])
        self.assertTrue(sink.last_submit_accepted)
        self.assertEqual(sink.last_status.written_sets, 4)
        self.assertEqual(len(repository.recording_status_payloads), 2)
        self.assertEqual(repository.recording_status_payloads[-1]["queue_high_watermark"], 3)

    def test_composite_sink_fans_out_to_repository_and_recording(self) -> None:
        repository = _FakeRepository()
        recording_status = RecordingStatus(
            enabled=True,
            active=False,
            failed=True,
            overflow_policy="fail_recording_keep_stream",
            queue_maxsize=4,
            queue_size=0,
            queue_high_watermark=4,
            submitted_sets=10,
            written_sets=7,
            dropped_sets=1,
            queue_full_events=1,
            first_failure_at_set=22,
            last_error="queue full",
        )
        recording_sink = _FakeRecordingSink(accepted=False, status=recording_status)
        composite = CompositeAlignedSetSink(
            [
                RepositoryAlignedSetSink(repository),
                RecordingAlignedSetSink(repository, recording_sink),
            ]
        )
        event = AlignedSetEvent(
            aligned_set=AlignedFrameSet(
                set_id=22,
                reference_camera_id="cam-a",
                reference_timestamp_s=4.2,
                skew_ms=1.5,
            ),
            sync_snapshot={"aligned_sets": 11},
            camera_snapshot={"cam-a": {"processed": 11}},
        )

        composite.publish(event)

        self.assertEqual(len(repository.published), 1)
        published_set, sync_snapshot, camera_snapshot = repository.published[0]
        self.assertEqual(published_set.set_id, 22)
        self.assertEqual(sync_snapshot["aligned_sets"], 11)
        self.assertEqual(camera_snapshot["cam-a"]["processed"], 11)
        self.assertEqual(recording_sink.submitted_set_ids, [22])
        self.assertEqual(repository.recording_status_payloads[-1]["last_error"], "queue full")


if __name__ == "__main__":
    unittest.main()

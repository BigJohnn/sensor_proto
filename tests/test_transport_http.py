from __future__ import annotations

import unittest

from sensor_proto.config import CameraConfig, RecordingConfig, RunConfig, StreamConfig, SyncConfig
from sensor_proto.recording import RecordingStatus
from sensor_proto.transport import build_http_stream_runtime


class _FakeServer:
    def __init__(self, server_address, repository, dashboard_html: str) -> None:
        self.server_address = server_address
        self.repository = repository
        self.dashboard_html = dashboard_html


class _FakeRecordingSink:
    def __init__(self, status: RecordingStatus) -> None:
        self._status = status
        self.submitted = 0

    def submit(self, aligned_set) -> bool:
        self.submitted += 1
        return True

    def status(self) -> RecordingStatus:
        return self._status


class TransportHttpTests(unittest.TestCase):
    def test_build_http_stream_runtime_initializes_disabled_recording_health(self) -> None:
        config = RunConfig(
            cameras=[
                CameraConfig(
                    id="cam-a",
                    kind="mock",
                    model="mock-camera",
                    fps=30,
                    width=640,
                    height=480,
                    capture_image_data=True,
                )
            ],
            duration_s=0.0,
            sync=SyncConfig(),
            stream=StreamConfig(host="127.0.0.1", port=8787),
            recording=RecordingConfig(enabled=False),
        )

        runtime = build_http_stream_runtime(config, recording_sink=None, server_factory=_FakeServer)

        self.assertIsNone(runtime.recording_publish_sink)
        self.assertFalse(runtime.repository.health_payload()["recording"]["enabled"])
        self.assertEqual(runtime.server.server_address, ("127.0.0.1", 8787))

    def test_build_http_stream_runtime_wires_recording_sink_status(self) -> None:
        config = RunConfig(
            cameras=[
                CameraConfig(
                    id="cam-a",
                    kind="mock",
                    model="mock-camera",
                    fps=30,
                    width=640,
                    height=480,
                    capture_image_data=True,
                )
            ],
            duration_s=0.0,
            sync=SyncConfig(),
            stream=StreamConfig(host="127.0.0.1", port=8788),
            recording=RecordingConfig(enabled=True),
        )
        recording_sink = _FakeRecordingSink(
            RecordingStatus(
                enabled=True,
                active=True,
                failed=False,
                overflow_policy="fail_recording_keep_stream",
                queue_maxsize=8,
                queue_size=1,
                queue_high_watermark=2,
                submitted_sets=3,
                written_sets=2,
                dropped_sets=0,
                queue_full_events=0,
                first_failure_at_set=None,
                last_error=None,
            )
        )

        runtime = build_http_stream_runtime(config, recording_sink=recording_sink, server_factory=_FakeServer)

        assert runtime.recording_publish_sink is not None
        self.assertEqual(runtime.recording_publish_sink.last_status.written_sets, 2)
        self.assertTrue(runtime.repository.health_payload()["recording"]["enabled"])
        self.assertEqual(runtime.server.server_address, ("127.0.0.1", 8788))


if __name__ == "__main__":
    unittest.main()

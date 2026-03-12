from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sensor_proto.cameras.realsense_discovery import RealSenseDeviceInfo, canonicalize_realsense_model
from sensor_proto.recording import RecordingStatus
from sensor_proto.stream_main import (
    build_realsense_stream_config_payload,
    close_recording_sink,
    parse_args,
    prepare_stream_runtime_config,
)
from sensor_proto.stream_server import AlignedSetRepository


class _FakeRecordingSink:
    def __init__(self, status: RecordingStatus) -> None:
        self._status = status
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def status(self) -> RecordingStatus:
        return self._status


class StreamAutoConfigTests(unittest.TestCase):
    def test_parse_args_accepts_stop_after_aligned_sets(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "stream_main.py",
                "--config",
                "configs/realsense-8cam-stream.json",
                "--stop-after-aligned-sets",
                "300",
            ],
        ):
            args = parse_args()

        self.assertEqual(args.config, "configs/realsense-8cam-stream.json")
        self.assertEqual(args.stop_after_aligned_sets, 300)

    def test_canonicalize_realsense_model_normalizes_sdk_names(self) -> None:
        self.assertEqual(canonicalize_realsense_model("Intel RealSense D435I"), "realsense-d435i")
        self.assertEqual(canonicalize_realsense_model("Intel RealSense D435IF"), "realsense-d435if")

    def test_build_realsense_stream_config_payload_replaces_camera_inventory(self) -> None:
        template_payload = {
            "duration_s": 30.0,
            "queue_size": 320,
            "stream": {
                "port": 9898,
                "client_refresh_ms": 180,
            },
            "sync": {
                "enabled": True,
                "tolerance_ms": 45.0,
                "reference_camera_id": "rs-07",
            },
            "cameras": [
                {
                    "id": "rs-00",
                    "kind": "realsense",
                    "model": "realsense-d435i",
                    "serial": "old-0",
                    "fps": 30,
                    "width": 640,
                    "height": 480,
                }
            ],
        }
        devices = [
            RealSenseDeviceInfo(
                serial="111",
                name="Intel RealSense D435I",
                model="realsense-d435i",
                physical_port="2-1",
            ),
            RealSenseDeviceInfo(
                serial="222",
                name="Intel RealSense D435IF",
                model="realsense-d435if",
                physical_port="2-2",
            ),
        ]

        payload = build_realsense_stream_config_payload(template_payload, devices)

        self.assertEqual(payload["duration_s"], 0.0)
        self.assertEqual(payload["queue_size"], 320)
        self.assertEqual(payload["sync"]["reference_camera_id"], "rs-00")
        self.assertEqual(payload["stream"]["port"], 9898)
        self.assertEqual(payload["stream"]["client_refresh_ms"], 180)
        self.assertEqual(payload["stream"]["preview_max_width"], 1280)
        self.assertEqual(payload["stream"]["preview_max_height"], 720)
        self.assertEqual(payload["stream"]["preview_jpeg_quality"], 72)
        self.assertEqual(len(payload["cameras"]), 2)
        self.assertEqual(payload["cameras"][0]["serial"], "111")
        self.assertEqual(payload["cameras"][1]["model"], "realsense-d435if")
        self.assertTrue(payload["cameras"][0]["capture_image_data"])
        self.assertEqual(payload["device_inventory"][1]["serial"], "222")

    def test_prepare_stream_runtime_config_writes_generated_payload(self) -> None:
        template_payload = {
            "duration_s": 30.0,
            "queue_size": 320,
            "cameras": [
                {
                    "id": "rs-00",
                    "kind": "realsense",
                    "model": "realsense-d435i",
                    "serial": "old-0",
                    "fps": 30,
                    "width": 640,
                    "height": 480,
                },
                {
                    "id": "rs-01",
                    "kind": "realsense",
                    "model": "realsense-d435i",
                    "serial": "old-1",
                    "fps": 30,
                    "width": 640,
                    "height": 480,
                },
            ],
        }
        devices = [
            RealSenseDeviceInfo(
                serial="111",
                name="Intel RealSense D435I",
                model="realsense-d435i",
                physical_port="2-1",
            ),
            RealSenseDeviceInfo(
                serial="222",
                name="Intel RealSense D435IF",
                model="realsense-d435if",
                physical_port="2-2",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "template.json"
            generated_path = Path(tmpdir) / "generated.json"
            template_path.write_text(json.dumps(template_payload), encoding="utf-8")

            with patch("sensor_proto.stream_main.discover_realsense_devices", return_value=devices):
                runtime_path = prepare_stream_runtime_config(
                    template_path=str(template_path),
                    generated_config_path=str(generated_path),
                )

            self.assertEqual(runtime_path, str(generated_path))
            payload = json.loads(generated_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["generated_from"], str(template_path))
            self.assertEqual([camera["serial"] for camera in payload["cameras"]], ["111", "222"])

    def test_prepare_stream_runtime_config_enforces_expected_count_when_requested(self) -> None:
        template_payload = {
            "cameras": [
                {
                    "id": "rs-00",
                    "kind": "realsense",
                    "model": "realsense-d435i",
                    "serial": "old-0",
                    "fps": 30,
                    "width": 640,
                    "height": 480,
                }
            ]
        }
        devices = [
            RealSenseDeviceInfo(
                serial="111",
                name="Intel RealSense D435I",
                model="realsense-d435i",
                physical_port="2-1",
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "template.json"
            generated_path = Path(tmpdir) / "generated.json"
            template_path.write_text(json.dumps(template_payload), encoding="utf-8")

            with patch("sensor_proto.stream_main.discover_realsense_devices", return_value=devices):
                with self.assertRaises(RuntimeError):
                    prepare_stream_runtime_config(
                        template_path=str(template_path),
                        generated_config_path=str(generated_path),
                        expected_cameras=2,
                    )

    def test_close_recording_sink_updates_repository_health(self) -> None:
        repository = AlignedSetRepository(camera_ids=["rs-00"], recent_sets=1)
        sink = _FakeRecordingSink(
            RecordingStatus(
                enabled=True,
                active=False,
                failed=True,
                overflow_policy="fail_recording_keep_stream",
                queue_maxsize=32,
                queue_size=0,
                queue_high_watermark=12,
                submitted_sets=20,
                written_sets=11,
                dropped_sets=1,
                queue_full_events=1,
                first_failure_at_set=42,
                last_error="recording queue full",
            )
        )

        status = close_recording_sink(sink, repository)

        assert status is not None
        self.assertTrue(sink.closed)
        self.assertTrue(status.failed)
        health = repository.health_payload()["recording"]
        self.assertEqual(health["queue_high_watermark"], 12)
        self.assertEqual(health["first_failure_at_set"], 42)
        self.assertEqual(health["last_error"], "recording queue full")


if __name__ == "__main__":
    unittest.main()

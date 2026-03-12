from __future__ import annotations

import unittest
from unittest.mock import patch

from sensor_proto.models import AlignedFrameSet, Frame
from sensor_proto.stream_server import AlignedSetRepository, encode_bgr_frame_as_bmp


class StreamServiceTests(unittest.TestCase):
    def test_encode_bgr_frame_as_bmp_returns_bitmap_payload(self) -> None:
        frame = Frame(
            camera_id="cam-a",
            camera_kind="mock",
            sequence=1,
            created_at=1.0,
            payload_size=12,
            width=2,
            height=2,
            pixel_format="bgr8",
            image_data=bytes(
                [
                    0,
                    0,
                    255,
                    0,
                    255,
                    0,
                    255,
                    0,
                    0,
                    255,
                    255,
                    255,
                ]
            ),
        )

        payload = encode_bgr_frame_as_bmp(frame)

        self.assertEqual(payload[:2], b"BM")
        self.assertGreater(len(payload), 54)

    def test_repository_exposes_latest_aligned_set_payload(self) -> None:
        repository = AlignedSetRepository(camera_ids=["cam-a", "cam-b"], recent_sets=2)
        repository.set_recording_status(
            {
                "enabled": True,
                "active": True,
                "failed": False,
                "overflow_policy": "fail_recording_keep_stream",
                "queue_maxsize": 8,
                "queue_size": 1,
                "queue_high_watermark": 4,
                "submitted_sets": 3,
                "written_sets": 2,
                "dropped_sets": 0,
                "queue_full_events": 0,
                "first_failure_at_set": None,
                "last_error": None,
            }
        )
        aligned_set = AlignedFrameSet(
            set_id=3,
            reference_camera_id="cam-a",
            reference_timestamp_s=123.456,
            skew_ms=7.5,
            frames={
                "cam-a": Frame(
                    camera_id="cam-a",
                    camera_kind="mock",
                    sequence=10,
                    created_at=1.0,
                    payload_size=3,
                    sensor_serial="mock-a",
                    frame_counter=10,
                    device_timestamp_ms=1000.0,
                    timestamp_domain="mock-device-clock",
                    width=1,
                    height=1,
                    pixel_format="bgr8",
                    image_data=b"\x00\x00\x00",
                ),
                "cam-b": Frame(
                    camera_id="cam-b",
                    camera_kind="mock",
                    sequence=11,
                    created_at=1.0,
                    payload_size=3,
                    sensor_serial="mock-b",
                    frame_counter=11,
                    device_timestamp_ms=1008.0,
                    timestamp_domain="mock-device-clock",
                    width=1,
                    height=1,
                    pixel_format="bgr8",
                    image_data=b"\x00\x00\x00",
                ),
            },
            offsets_ms={"cam-a": 0.0, "cam-b": 8.0},
        )

        with patch("sensor_proto.stream_server.build_preview_frame_as_jpeg", return_value=b"preview-jpeg"):
            repository.publish(
                aligned_set,
                sync_snapshot={"aligned_sets": 1, "warnings": []},
                camera_snapshot={"cam-a": {"processed": 1}, "cam-b": {"processed": 1}},
            )

        payload = repository.latest_payload()

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["set_id"], 3)
        self.assertEqual(payload["camera_order"], ["cam-a", "cam-b"])
        self.assertEqual(payload["offsets_ms"]["cam-b"], 8.0)
        self.assertEqual(payload["frames"]["cam-a"]["sensor_serial"], "mock-a")

        preview_payload, preview_headers = repository.get_latest_preview_jpeg()
        self.assertEqual(preview_payload, b"preview-jpeg")
        self.assertEqual(preview_headers["X-SensorProto-Set-Id"], "3")
        self.assertEqual(preview_headers["X-SensorProto-Camera-Count"], "2")
        preview_health = repository.health_payload()["preview"]
        self.assertTrue(preview_health["available"])
        self.assertIsNone(preview_health["last_error"])
        self.assertEqual(preview_health["max_width"], 1280)
        self.assertEqual(preview_health["max_height"], 720)
        self.assertEqual(preview_health["jpeg_quality"], 72)
        self.assertEqual(preview_health["last_size_bytes"], len(b"preview-jpeg"))
        self.assertEqual(preview_health["encoded_frames"], 1)
        self.assertEqual(preview_health["publish_rate_hz"], 0.0)
        recording_health = repository.health_payload()["recording"]
        self.assertTrue(recording_health["enabled"])
        self.assertEqual(recording_health["queue_size"], 1)
        self.assertEqual(recording_health["queue_high_watermark"], 4)
        self.assertEqual(recording_health["written_sets"], 2)


if __name__ == "__main__":
    unittest.main()

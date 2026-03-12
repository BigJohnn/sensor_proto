from __future__ import annotations

import urllib.error
import unittest
from unittest.mock import patch

from sensor_proto.stream_client import AlignedStreamClient, StreamClientError


class StreamClientTests(unittest.TestCase):
    def test_get_latest_aligned_frames_returns_frames_and_unified_timestamp(self) -> None:
        client = AlignedStreamClient("http://127.0.0.1:8787")
        latest_payload = {
            "set_id": 12,
            "reference_timestamp_s": 123.456,
            "skew_ms": 8.5,
            "camera_order": ["rs-00", "rs-01"],
            "offsets_ms": {"rs-00": 0.0, "rs-01": 8.5},
            "frames": {
                "rs-00": {"device_timestamp_ms": 1000.0},
                "rs-01": {"device_timestamp_ms": 1008.5},
            },
        }

        with (
            patch.object(client, "_get_json", return_value=latest_payload),
            patch.object(client, "_get_bytes", side_effect=[b"bmp-a", b"bmp-b"]),
            patch.object(client, "_decode_bmp", side_effect=["frame-a", "frame-b"]),
        ):
            frames, timestamp = client.get_latest_aligned_frames()

        self.assertEqual(timestamp, 123.456)
        self.assertEqual(frames, {"rs-00": "frame-a", "rs-01": "frame-b"})

    def test_get_latest_aligned_set_returns_debug_metadata(self) -> None:
        client = AlignedStreamClient("http://127.0.0.1:8787")
        latest_payload = {
            "set_id": 5,
            "reference_timestamp_s": 55.0,
            "skew_ms": 3.0,
            "camera_order": ["rs-00"],
            "offsets_ms": {"rs-00": 0.0},
            "frames": {"rs-00": {"device_timestamp_ms": 999.0}},
        }

        with (
            patch.object(client, "_get_json", return_value=latest_payload),
            patch.object(client, "_get_bytes", return_value=b"bmp"),
            patch.object(client, "_decode_bmp", return_value="frame"),
        ):
            aligned = client.get_latest_aligned_set()

        self.assertEqual(aligned.set_id, 5)
        self.assertEqual(aligned.timestamp, 55.0)
        self.assertEqual(aligned.offsets_ms, {"rs-00": 0.0})
        self.assertEqual(aligned.device_timestamps_ms, {"rs-00": 999.0})
        self.assertEqual(aligned.frames["rs-00"], "frame")

    def test_get_bytes_wraps_url_errors(self) -> None:
        client = AlignedStreamClient("http://127.0.0.1:8787")
        with patch("sensor_proto.stream_client.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(StreamClientError):
                client._get_bytes("/api/health")

    def test_get_latest_preview_returns_single_image_and_metadata(self) -> None:
        client = AlignedStreamClient("http://127.0.0.1:8787")
        preview_headers = {
            "X-SensorProto-Set-Id": "21",
            "X-SensorProto-Reference-Timestamp-S": "456.789",
            "X-SensorProto-Skew-Ms": "9.250",
            "X-SensorProto-Camera-Count": "8",
        }

        with (
            patch.object(client, "_get_bytes_with_headers", return_value=(b"jpeg", preview_headers)),
            patch.object(client, "_decode_image", return_value="preview-frame"),
        ):
            preview = client.get_latest_preview()

        self.assertEqual(preview.set_id, 21)
        self.assertEqual(preview.timestamp, 456.789)
        self.assertEqual(preview.skew_ms, 9.25)
        self.assertEqual(preview.camera_count, 8)
        self.assertEqual(preview.frame, "preview-frame")


if __name__ == "__main__":
    unittest.main()

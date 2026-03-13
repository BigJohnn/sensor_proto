from __future__ import annotations

import json
import unittest

from sensor_proto.models import AlignedFrameSet, Frame
from sensor_proto.transport.zmq.encoding import decode_aligned_set_multipart, encode_aligned_set_multipart
from sensor_proto.transport.zmq.protocol import PAYLOAD_ENCODING_JPEG, PROTOCOL_NAME, PROTOCOL_VERSION


class ZmqEncodingTests(unittest.TestCase):
    def test_encode_aligned_set_multipart_uses_contract_layout(self) -> None:
        aligned_set = AlignedFrameSet(
            set_id=7,
            reference_camera_id="cam-a",
            reference_timestamp_s=123.456,
            skew_ms=2.5,
            frames={
                "cam-a": Frame(
                    camera_id="cam-a",
                    camera_kind="mock",
                    sequence=1,
                    created_at=1.0,
                    payload_size=3,
                    device_timestamp_ms=1000.0,
                    width=1,
                    height=1,
                    pixel_format="bgr8",
                    image_data=b"\x00\x00\x00",
                ),
                "cam-b": Frame(
                    camera_id="cam-b",
                    camera_kind="mock",
                    sequence=2,
                    created_at=1.0,
                    payload_size=3,
                    device_timestamp_ms=1008.0,
                    width=1,
                    height=1,
                    pixel_format="bgr8",
                    image_data=b"\x00\x00\x00",
                ),
            },
            offsets_ms={"cam-a": 0.0, "cam-b": 8.0},
        )

        def fake_image_encoder(frame: Frame, jpeg_quality: int) -> bytes:
            return f"{frame.camera_id}:{jpeg_quality}".encode("utf-8")

        parts = encode_aligned_set_multipart(
            aligned_set,
            ["cam-a", "cam-b"],
            jpeg_quality=77,
            image_encoder=fake_image_encoder,
        )

        self.assertEqual(len(parts), 5)
        envelope = json.loads(parts[0].decode("utf-8"))
        self.assertEqual(envelope["protocol"], PROTOCOL_NAME)
        self.assertEqual(envelope["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(envelope["camera_count"], 2)
        self.assertEqual(envelope["camera_order"], ["cam-a", "cam-b"])

        cam_a_meta = json.loads(parts[1].decode("utf-8"))
        self.assertEqual(cam_a_meta["camera_id"], "cam-a")
        self.assertEqual(cam_a_meta["offset_ms"], 0.0)
        self.assertEqual(cam_a_meta["payload_encoding"], PAYLOAD_ENCODING_JPEG)
        self.assertEqual(cam_a_meta["payload_size_bytes"], len(parts[2]))
        self.assertEqual(parts[2], b"cam-a:77")

        cam_b_meta = json.loads(parts[3].decode("utf-8"))
        self.assertEqual(cam_b_meta["camera_id"], "cam-b")
        self.assertEqual(cam_b_meta["offset_ms"], 8.0)
        self.assertEqual(parts[4], b"cam-b:77")

        decoded = decode_aligned_set_multipart(
            parts,
            image_decoder=lambda payload, metadata: payload.decode("utf-8"),
        )
        self.assertEqual(decoded.envelope["set_id"], 7)
        self.assertEqual([camera.metadata["camera_id"] for camera in decoded.cameras], ["cam-a", "cam-b"])
        self.assertEqual(decoded.cameras[0].decoded_image, "cam-a:77")
        self.assertEqual(decoded.cameras[1].decoded_image, "cam-b:77")

    def test_decode_aligned_set_multipart_ignores_unknown_fields_within_protocol_version(self) -> None:
        parts = [
            json.dumps(
                {
                    "protocol": PROTOCOL_NAME,
                    "protocol_version": PROTOCOL_VERSION,
                    "set_id": 1,
                    "reference_camera_id": "cam-a",
                    "reference_timestamp_s": 1.0,
                    "skew_ms": 0.0,
                    "camera_count": 1,
                    "camera_order": ["cam-a"],
                    "future_field": "ok",
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "camera_id": "cam-a",
                    "device_timestamp_ms": 1.0,
                    "offset_ms": 0.0,
                    "width": 1,
                    "height": 1,
                    "pixel_format": "bgr8",
                    "payload_encoding": PAYLOAD_ENCODING_JPEG,
                    "payload_size_bytes": 4,
                    "future_camera_field": "ok",
                }
            ).encode("utf-8"),
            b"jpeg",
        ]

        decoded = decode_aligned_set_multipart(parts)

        self.assertEqual(decoded.envelope["future_field"], "ok")
        self.assertEqual(decoded.cameras[0].metadata["future_camera_field"], "ok")

    def test_encode_aligned_set_multipart_rejects_missing_camera(self) -> None:
        aligned_set = AlignedFrameSet(
            set_id=8,
            reference_camera_id="cam-a",
            reference_timestamp_s=1.0,
            skew_ms=0.0,
            frames={},
            offsets_ms={},
        )

        with self.assertRaisesRegex(ValueError, "missing camera"):
            encode_aligned_set_multipart(aligned_set, ["cam-a"], image_encoder=lambda frame, quality: b"jpeg")

    def test_encode_aligned_set_multipart_rejects_missing_offset(self) -> None:
        aligned_set = AlignedFrameSet(
            set_id=9,
            reference_camera_id="cam-a",
            reference_timestamp_s=1.0,
            skew_ms=0.0,
            frames={
                "cam-a": Frame(
                    camera_id="cam-a",
                    camera_kind="mock",
                    sequence=1,
                    created_at=1.0,
                    payload_size=3,
                    width=1,
                    height=1,
                    pixel_format="bgr8",
                    image_data=b"\x00\x00\x00",
                )
            },
            offsets_ms={},
        )

        with self.assertRaisesRegex(ValueError, "missing offset"):
            encode_aligned_set_multipart(aligned_set, ["cam-a"], image_encoder=lambda frame, quality: b"jpeg")

    def test_decode_aligned_set_multipart_rejects_part_count_mismatch(self) -> None:
        envelope = {
            "protocol": PROTOCOL_NAME,
            "protocol_version": PROTOCOL_VERSION,
            "set_id": 1,
            "reference_camera_id": "cam-a",
            "reference_timestamp_s": 1.0,
            "skew_ms": 0.0,
            "camera_count": 1,
            "camera_order": ["cam-a"],
        }
        with self.assertRaisesRegex(ValueError, "part count"):
            decode_aligned_set_multipart([json.dumps(envelope).encode("utf-8")])

    def test_decode_aligned_set_multipart_rejects_camera_order_mismatch(self) -> None:
        parts = [
            json.dumps(
                {
                    "protocol": PROTOCOL_NAME,
                    "protocol_version": PROTOCOL_VERSION,
                    "set_id": 1,
                    "reference_camera_id": "cam-a",
                    "reference_timestamp_s": 1.0,
                    "skew_ms": 0.0,
                    "camera_count": 1,
                    "camera_order": ["cam-a"],
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "camera_id": "cam-b",
                    "device_timestamp_ms": 1.0,
                    "offset_ms": 0.0,
                    "width": 1,
                    "height": 1,
                    "pixel_format": "bgr8",
                    "payload_encoding": PAYLOAD_ENCODING_JPEG,
                    "payload_size_bytes": 4,
                }
            ).encode("utf-8"),
            b"jpeg",
        ]
        with self.assertRaisesRegex(ValueError, "camera_order"):
            decode_aligned_set_multipart(parts)

    def test_decode_aligned_set_multipart_rejects_unsupported_encoding(self) -> None:
        parts = [
            json.dumps(
                {
                    "protocol": PROTOCOL_NAME,
                    "protocol_version": PROTOCOL_VERSION,
                    "set_id": 1,
                    "reference_camera_id": "cam-a",
                    "reference_timestamp_s": 1.0,
                    "skew_ms": 0.0,
                    "camera_count": 1,
                    "camera_order": ["cam-a"],
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "camera_id": "cam-a",
                    "device_timestamp_ms": 1.0,
                    "offset_ms": 0.0,
                    "width": 1,
                    "height": 1,
                    "pixel_format": "bgr8",
                    "payload_encoding": "bmp",
                    "payload_size_bytes": 4,
                }
            ).encode("utf-8"),
            b"jpeg",
        ]
        with self.assertRaisesRegex(ValueError, "payload_encoding"):
            decode_aligned_set_multipart(parts)

    def test_decode_aligned_set_multipart_rejects_unsupported_protocol_version(self) -> None:
        parts = [
            json.dumps(
                {
                    "protocol": PROTOCOL_NAME,
                    "protocol_version": PROTOCOL_VERSION + 1,
                    "set_id": 1,
                    "reference_camera_id": "cam-a",
                    "reference_timestamp_s": 1.0,
                    "skew_ms": 0.0,
                    "camera_count": 1,
                    "camera_order": ["cam-a"],
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "camera_id": "cam-a",
                    "device_timestamp_ms": 1.0,
                    "offset_ms": 0.0,
                    "width": 1,
                    "height": 1,
                    "pixel_format": "bgr8",
                    "payload_encoding": PAYLOAD_ENCODING_JPEG,
                    "payload_size_bytes": 4,
                }
            ).encode("utf-8"),
            b"jpeg",
        ]
        with self.assertRaisesRegex(ValueError, "protocol_version"):
            decode_aligned_set_multipart(parts)

    def test_decode_aligned_set_multipart_rejects_payload_size_mismatch(self) -> None:
        parts = [
            json.dumps(
                {
                    "protocol": PROTOCOL_NAME,
                    "protocol_version": PROTOCOL_VERSION,
                    "set_id": 1,
                    "reference_camera_id": "cam-a",
                    "reference_timestamp_s": 1.0,
                    "skew_ms": 0.0,
                    "camera_count": 1,
                    "camera_order": ["cam-a"],
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "camera_id": "cam-a",
                    "device_timestamp_ms": 1.0,
                    "offset_ms": 0.0,
                    "width": 1,
                    "height": 1,
                    "pixel_format": "bgr8",
                    "payload_encoding": PAYLOAD_ENCODING_JPEG,
                    "payload_size_bytes": 999,
                }
            ).encode("utf-8"),
            b"jpeg",
        ]
        with self.assertRaisesRegex(ValueError, "payload size"):
            decode_aligned_set_multipart(parts)

    def test_decode_aligned_set_multipart_rejects_malformed_metadata_blob(self) -> None:
        with self.assertRaisesRegex(ValueError, "envelope metadata"):
            decode_aligned_set_multipart([b"{not-json"])


if __name__ == "__main__":
    unittest.main()

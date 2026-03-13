from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Callable

from sensor_proto.models import AlignedFrameSet, Frame
from sensor_proto.transport.zmq.protocol import PAYLOAD_ENCODING_JPEG, PROTOCOL_NAME, PROTOCOL_VERSION


@dataclass(slots=True)
class DecodedCameraPayload:
    metadata: dict[str, object]
    payload: bytes
    decoded_image: object | None = None


@dataclass(slots=True)
class DecodedAlignedSetMultipart:
    envelope: dict[str, object]
    cameras: list[DecodedCameraPayload]


def encode_json_metadata(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode_json_metadata(payload: bytes, label: str) -> dict[str, object]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON metadata.") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} must decode to a JSON object.")
    return decoded


def build_envelope_metadata(aligned_set: AlignedFrameSet, camera_order: list[str]) -> dict[str, object]:
    return {
        "protocol": PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "set_id": aligned_set.set_id,
        "reference_camera_id": aligned_set.reference_camera_id,
        "reference_timestamp_s": aligned_set.reference_timestamp_s,
        "skew_ms": aligned_set.skew_ms,
        "camera_count": len(camera_order),
        "camera_order": list(camera_order),
    }


def build_camera_metadata(frame: Frame, offset_ms: float, payload_size_bytes: int) -> dict[str, object]:
    if frame.width is None or frame.height is None or frame.pixel_format is None:
        raise ValueError(f"{frame.camera_id} metadata is incomplete for ZMQ transport encoding.")
    return {
        "camera_id": frame.camera_id,
        "device_timestamp_ms": frame.device_timestamp_ms,
        "offset_ms": offset_ms,
        "width": frame.width,
        "height": frame.height,
        "pixel_format": frame.pixel_format,
        "payload_encoding": PAYLOAD_ENCODING_JPEG,
        "payload_size_bytes": payload_size_bytes,
    }


def encode_aligned_set_multipart(
    aligned_set: AlignedFrameSet,
    camera_order: list[str],
    *,
    jpeg_quality: int = 80,
    image_encoder: Callable[[Frame, int], bytes] | None = None,
) -> list[bytes]:
    if not camera_order:
        raise ValueError("camera_order must not be empty.")
    if image_encoder is None:
        image_encoder = encode_frame_as_jpeg

    parts = [encode_json_metadata(build_envelope_metadata(aligned_set, camera_order))]
    for camera_id in camera_order:
        frame = aligned_set.frames.get(camera_id)
        if frame is None:
            raise ValueError(f"Aligned frame set {aligned_set.set_id} is missing camera {camera_id}.")
        if camera_id not in aligned_set.offsets_ms:
            raise ValueError(f"Aligned frame set {aligned_set.set_id} is missing offset for camera {camera_id}.")
        payload = image_encoder(frame, jpeg_quality)
        parts.append(encode_json_metadata(build_camera_metadata(frame, aligned_set.offsets_ms[camera_id], len(payload))))
        parts.append(payload)
    return parts


def encode_frame_as_jpeg(frame: Frame, jpeg_quality: int = 80) -> bytes:
    if frame.image_data is None or frame.width is None or frame.height is None:
        raise ValueError(f"{frame.camera_id} does not include image data.")
    if frame.pixel_format != "bgr8":
        raise ValueError(f"Unsupported pixel format for ZMQ JPEG transport: {frame.pixel_format}")
    expected_size = frame.width * frame.height * 3
    if len(frame.image_data) != expected_size:
        raise ValueError(f"{frame.camera_id} image buffer size {len(frame.image_data)} does not match expected {expected_size}.")
    cv2 = _load_cv2_module()
    np = _load_numpy_module()
    image = np.frombuffer(frame.image_data, dtype=np.uint8).reshape((frame.height, frame.width, 3))
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not ok:
        raise ValueError(f"OpenCV failed to encode JPEG payload for {frame.camera_id}.")
    return encoded.tobytes()


def decode_aligned_set_multipart(
    parts: list[bytes],
    *,
    image_decoder: Callable[[bytes, dict[str, object]], object] | None = None,
) -> DecodedAlignedSetMultipart:
    if not parts:
        raise ValueError("Multipart payload must contain at least one envelope metadata part.")
    envelope = decode_json_metadata(parts[0], "envelope metadata")
    if envelope.get("protocol") != PROTOCOL_NAME:
        raise ValueError("Envelope metadata has unsupported protocol.")
    if int(envelope.get("protocol_version", -1)) != PROTOCOL_VERSION:
        raise ValueError("Envelope metadata has unsupported protocol_version.")
    camera_order_raw = envelope.get("camera_order")
    if not isinstance(camera_order_raw, list) or not all(isinstance(camera_id, str) for camera_id in camera_order_raw):
        raise ValueError("Envelope metadata must include a string camera_order list.")
    camera_order = list(camera_order_raw)
    camera_count = int(envelope.get("camera_count", -1))
    if camera_count != len(camera_order):
        raise ValueError("Envelope metadata camera_count does not match camera_order length.")
    expected_part_count = 1 + camera_count * 2
    if len(parts) != expected_part_count:
        raise ValueError("Multipart payload part count does not match envelope camera_count.")

    cameras: list[DecodedCameraPayload] = []
    for index, camera_id in enumerate(camera_order):
        metadata_part = parts[1 + index * 2]
        payload_part = parts[2 + index * 2]
        metadata = decode_json_metadata(metadata_part, f"camera metadata[{index}]")
        if metadata.get("camera_id") != camera_id:
            raise ValueError("Camera metadata order does not match envelope camera_order.")
        if metadata.get("payload_encoding") != PAYLOAD_ENCODING_JPEG:
            raise ValueError("Camera metadata has unsupported payload_encoding.")
        payload_size_bytes = int(metadata.get("payload_size_bytes", -1))
        if payload_size_bytes != len(payload_part):
            raise ValueError("Camera payload size does not match payload_size_bytes metadata.")
        decoded_image = image_decoder(payload_part, metadata) if image_decoder is not None else None
        cameras.append(DecodedCameraPayload(metadata=metadata, payload=payload_part, decoded_image=decoded_image))
    return DecodedAlignedSetMultipart(envelope=envelope, cameras=cameras)


def _load_cv2_module():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on runtime environment
        raise ValueError("ZMQ JPEG transport encoding requires cv2 in the stream service environment.") from exc
    return cv2


def _load_numpy_module():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on runtime environment
        raise ValueError("ZMQ JPEG transport encoding requires numpy in the stream service environment.") from exc
    return np

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


class StreamClientError(RuntimeError):
    pass


@dataclass(slots=True)
class AlignedFrameBundle:
    set_id: int
    timestamp: float
    frames: dict[str, Any]
    offsets_ms: dict[str, float]
    device_timestamps_ms: dict[str, float | None]
    skew_ms: float
    camera_order: list[str]
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class PreviewFrameBundle:
    set_id: int
    timestamp: float
    skew_ms: float
    camera_count: int
    frame: Any


class AlignedStreamClient:
    def __init__(self, base_url: str, timeout_s: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def get_latest_aligned_frames(self) -> tuple[dict[str, Any], float]:
        aligned = self.get_latest_aligned_set()
        return aligned.frames, aligned.timestamp

    def get_latest_aligned_set(self) -> AlignedFrameBundle:
        payload = self._get_json("/api/latest-set")
        set_id = int(payload["set_id"])
        camera_order = list(payload["camera_order"])
        frames: dict[str, Any] = {}
        for camera_id in camera_order:
            frame_path = f"/api/sets/{set_id}/frames/{parse.quote(camera_id, safe='')}.bmp"
            frames[camera_id] = self._decode_bmp(self._get_bytes(frame_path))
        device_timestamps_ms = {
            camera_id: payload["frames"][camera_id].get("device_timestamp_ms")
            for camera_id in camera_order
        }
        return AlignedFrameBundle(
            set_id=set_id,
            timestamp=float(payload["reference_timestamp_s"]),
            frames=frames,
            offsets_ms={camera_id: float(payload["offsets_ms"][camera_id]) for camera_id in camera_order},
            device_timestamps_ms=device_timestamps_ms,
            skew_ms=float(payload["skew_ms"]),
            camera_order=camera_order,
            raw_payload=payload,
        )

    def get_latest_preview(self) -> PreviewFrameBundle:
        payload, headers = self._get_bytes_with_headers("/api/preview.jpg")
        return PreviewFrameBundle(
            set_id=self._read_int_header(headers, "X-SensorProto-Set-Id"),
            timestamp=self._read_float_header(headers, "X-SensorProto-Reference-Timestamp-S"),
            skew_ms=self._read_float_header(headers, "X-SensorProto-Skew-Ms"),
            camera_count=self._read_int_header(headers, "X-SensorProto-Camera-Count"),
            frame=self._decode_image(payload),
        )

    def get_health(self) -> dict[str, Any]:
        return self._get_json("/api/health")

    def _get_json(self, path: str) -> dict[str, Any]:
        payload = self._get_bytes(path)
        return json.loads(payload.decode("utf-8"))

    def _get_bytes(self, path: str) -> bytes:
        payload, _ = self._get_bytes_with_headers(path)
        return payload

    def _get_bytes_with_headers(self, path: str) -> tuple[bytes, Any]:
        url = f"{self._base_url}{path}"
        try:
            with request.urlopen(url, timeout=self._timeout_s) as response:
                return response.read(), response.headers
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise StreamClientError(f"HTTP {exc.code} for {url}: {body}") from exc
        except error.URLError as exc:
            raise StreamClientError(f"Failed to reach stream service at {url}: {exc.reason}") from exc

    @staticmethod
    def _decode_image(payload: bytes):
        try:
            import cv2
            import numpy as np
        except ImportError as exc:  # pragma: no cover - depends on host environment
            raise StreamClientError("AlignedStreamClient requires numpy and cv2 on the host environment.") from exc

        encoded = np.frombuffer(payload, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            raise StreamClientError("OpenCV failed to decode image payload from stream service.")
        return frame

    @staticmethod
    def _decode_bmp(payload: bytes):
        return AlignedStreamClient._decode_image(payload)

    @staticmethod
    def _read_int_header(headers: Any, name: str) -> int:
        value = headers.get(name)
        if value is None:
            raise StreamClientError(f"Stream service response is missing required header: {name}")
        return int(value)

    @staticmethod
    def _read_float_header(headers: Any, name: str) -> float:
        value = headers.get(name)
        if value is None:
            raise StreamClientError(f"Stream service response is missing required header: {name}")
        return float(value)

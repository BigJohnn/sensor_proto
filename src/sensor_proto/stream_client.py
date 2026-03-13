from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request
from urllib.parse import urlparse

from sensor_proto.transport.zmq import decode_aligned_set_multipart


class StreamClientError(RuntimeError):
    pass


def resolve_zmq_endpoint(
    base_url: str,
    health_payload: dict[str, Any],
    *,
    explicit_endpoint: str | None = None,
) -> str:
    if explicit_endpoint:
        return explicit_endpoint
    transport = health_payload.get("transport")
    if not isinstance(transport, dict) or not transport.get("enabled") or transport.get("kind") != "zmq":
        raise StreamClientError("Stream service health does not advertise an enabled ZMQ transport.")
    port = transport.get("port")
    if port is None:
        raise StreamClientError("Stream service health is missing transport.port for ZMQ discovery.")
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        raise StreamClientError(f"Could not determine host from base URL: {base_url}")
    return f"tcp://{host}:{int(port)}"


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


class ZmqAlignedStreamClient:
    def __init__(
        self,
        endpoint: str,
        *,
        timeout_ms: int = 5000,
        zmq_module=None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout_ms = timeout_ms
        self._zmq_module = zmq_module
        self._context = None
        self._socket = None

    def open(self) -> None:
        if self._socket is not None:
            return
        zmq = self._zmq_module or self._load_zmq_module()
        self._context = zmq.Context.instance()
        self._socket = self._context.socket(zmq.SUB)
        self._socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self._socket.connect(self._endpoint)

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None
        self._context = None

    def recv_aligned_set(self, timeout_ms: int | None = None) -> AlignedFrameBundle:
        multipart = self._recv_multipart(timeout_ms=timeout_ms)
        decoded = decode_aligned_set_multipart(
            multipart,
            image_decoder=lambda payload, metadata: AlignedStreamClient._decode_image(payload),
        )
        camera_order = list(decoded.envelope["camera_order"])
        frames = {
            str(camera.metadata["camera_id"]): camera.decoded_image
            for camera in decoded.cameras
        }
        offsets_ms = {
            str(camera.metadata["camera_id"]): float(camera.metadata["offset_ms"])
            for camera in decoded.cameras
        }
        device_timestamps_ms = {
            str(camera.metadata["camera_id"]): (
                float(camera.metadata["device_timestamp_ms"])
                if camera.metadata.get("device_timestamp_ms") is not None
                else None
            )
            for camera in decoded.cameras
        }
        return AlignedFrameBundle(
            set_id=int(decoded.envelope["set_id"]),
            timestamp=float(decoded.envelope["reference_timestamp_s"]),
            frames=frames,
            offsets_ms=offsets_ms,
            device_timestamps_ms=device_timestamps_ms,
            skew_ms=float(decoded.envelope["skew_ms"]),
            camera_order=camera_order,
            raw_payload={
                "envelope": decoded.envelope,
                "cameras": [camera.metadata for camera in decoded.cameras],
            },
        )

    def get_next_aligned_set(self, timeout_ms: int | None = None) -> AlignedFrameBundle:
        return self.recv_aligned_set(timeout_ms=timeout_ms)

    def recv_aligned_frames(self, timeout_ms: int | None = None) -> tuple[dict[str, Any], float]:
        aligned = self.recv_aligned_set(timeout_ms=timeout_ms)
        return aligned.frames, aligned.timestamp

    def _recv_multipart(self, timeout_ms: int | None = None) -> list[bytes]:
        if self._socket is None:
            self.open()
        assert self._socket is not None
        zmq = self._zmq_module or self._load_zmq_module()
        effective_timeout_ms = self._timeout_ms if timeout_ms is None else int(timeout_ms)
        if hasattr(self._socket, "setsockopt") and hasattr(zmq, "RCVTIMEO"):
            self._socket.setsockopt(zmq.RCVTIMEO, effective_timeout_ms)
        try:
            return self._socket.recv_multipart()
        except Exception as exc:
            again_type = getattr(zmq, "Again", None)
            if again_type is not None and isinstance(exc, again_type):
                raise StreamClientError(
                    f"Timed out waiting for aligned-set multipart message from {self._endpoint} after {effective_timeout_ms}ms."
                ) from exc
            raise StreamClientError(f"Failed to receive ZMQ aligned-set message from {self._endpoint}: {exc}") from exc

    @staticmethod
    def _load_zmq_module():
        try:
            import zmq
        except ImportError as exc:  # pragma: no cover - depends on host environment
            raise StreamClientError("ZmqAlignedStreamClient requires the `pyzmq` package on the host environment.") from exc
        return zmq

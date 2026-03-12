from __future__ import annotations

import json
import struct
import threading
import time
from collections import OrderedDict
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from sensor_proto.models import AlignedFrameSet, Frame
from sensor_proto.preview import compute_grid_layout


def encode_bgr_frame_as_bmp(frame: Frame) -> bytes:
    if frame.image_data is None or frame.width is None or frame.height is None:
        raise ValueError(f"{frame.camera_id} does not include image data.")
    if frame.pixel_format != "bgr8":
        raise ValueError(f"Unsupported pixel format: {frame.pixel_format}")

    row_stride = frame.width * 3
    padded_row_stride = (row_stride + 3) & ~3
    pixel_bytes = bytearray()
    for row_index in range(frame.height - 1, -1, -1):
        start = row_index * row_stride
        end = start + row_stride
        pixel_bytes.extend(frame.image_data[start:end])
        pixel_bytes.extend(b"\x00" * (padded_row_stride - row_stride))

    image_size = len(pixel_bytes)
    file_size = 14 + 40 + image_size
    header = struct.pack(
        "<2sIHHI",
        b"BM",
        file_size,
        0,
        0,
        14 + 40,
    )
    dib = struct.pack(
        "<IIIHHIIIIII",
        40,
        frame.width,
        frame.height,
        1,
        24,
        0,
        image_size,
        2835,
        2835,
        0,
        0,
    )
    return header + dib + bytes(pixel_bytes)


def build_preview_frame_as_jpeg(
    aligned_set: AlignedFrameSet,
    camera_order: list[str],
    sync_snapshot: dict[str, object],
    max_width: int = 1600,
    max_height: int = 900,
    gap_px: int = 12,
    header_px: int = 72,
    jpeg_quality: int = 80,
) -> bytes:
    cv2 = _load_cv2_module()
    np = _load_numpy_module()
    preview_order = [camera_id for camera_id in camera_order if camera_id in aligned_set.frames]
    if not preview_order:
        raise ValueError("Aligned frame set does not contain previewable frames.")

    first_frame = aligned_set.frames[preview_order[0]]
    frame_height, frame_width = _frame_image_shape(first_frame)
    layout = compute_grid_layout(
        frame_width=frame_width,
        frame_height=frame_height,
        camera_count=len(preview_order),
        max_width=max_width,
        max_height=max_height,
        gap_px=gap_px,
        header_px=header_px,
    )
    canvas = np.zeros((layout.canvas_height, layout.canvas_width, 3), dtype=np.uint8)
    canvas[:] = (9, 17, 26)

    warnings_by_camera: dict[str, list[str]] = {}
    for warning in sync_snapshot.get("warnings", []):
        if not isinstance(warning, dict):
            continue
        camera_id = warning.get("camera_id")
        code = warning.get("code")
        if camera_id is None or code is None:
            continue
        warnings_by_camera.setdefault(str(camera_id), []).append(str(code))

    summary = (
        f"set={aligned_set.set_id}  ts={aligned_set.reference_timestamp_s:.3f}  "
        f"skew={aligned_set.skew_ms:.3f}ms  cams={len(preview_order)}  "
        f"aligned={int(sync_snapshot.get('aligned_sets', 0))}  dropped={int(sync_snapshot.get('dropped_frames', 0))}"
    )
    cv2.putText(canvas, summary, (gap_px, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (236, 242, 248), 2, cv2.LINE_AA)
    cv2.putText(
        canvas,
        "preview path: latest-only mosaic",
        (gap_px, 54),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (159, 177, 196),
        1,
        cv2.LINE_AA,
    )

    for index, camera_id in enumerate(preview_order):
        row = index // layout.cols
        col = index % layout.cols
        x = gap_px + col * (layout.cell_width + gap_px)
        y = header_px + gap_px + row * (layout.cell_height + gap_px)
        frame = aligned_set.frames[camera_id]
        image = _frame_to_ndarray(frame, np)
        resized = cv2.resize(image, (layout.cell_width, layout.cell_height), interpolation=cv2.INTER_AREA)
        canvas[y : y + layout.cell_height, x : x + layout.cell_width] = resized
        cv2.rectangle(canvas, (x, y), (x + layout.cell_width, y + layout.cell_height), (83, 209, 201), 1)

        offset_ms = aligned_set.offsets_ms.get(camera_id, 0.0)
        warning_codes = ",".join(warnings_by_camera.get(camera_id, []))
        label = f"{camera_id}  offset={offset_ms:.2f}ms"
        if warning_codes:
            label = f"{label}  warn={warning_codes}"
        cv2.putText(canvas, label, (x + 8, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 209, 102), 2, cv2.LINE_AA)

    ok, encoded = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not ok:
        raise ValueError("OpenCV failed to encode preview mosaic.")
    return encoded.tobytes()


def _frame_image_shape(frame: Frame) -> tuple[int, int]:
    if frame.image_data is None or frame.width is None or frame.height is None:
        raise ValueError(f"{frame.camera_id} does not include image data.")
    if frame.pixel_format != "bgr8":
        raise ValueError(f"Unsupported pixel format: {frame.pixel_format}")
    expected_size = frame.width * frame.height * 3
    if len(frame.image_data) != expected_size:
        raise ValueError(f"{frame.camera_id} image buffer size {len(frame.image_data)} does not match expected {expected_size}.")
    return frame.height, frame.width


def _frame_to_ndarray(frame: Frame, np):
    frame_height, frame_width = _frame_image_shape(frame)
    return np.frombuffer(frame.image_data, dtype=np.uint8).reshape((frame_height, frame_width, 3))


def _load_cv2_module():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on runtime environment
        raise ValueError("Preview mosaic rendering requires cv2 in the stream service environment.") from exc
    return cv2


def _load_numpy_module():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on runtime environment
        raise ValueError("Preview mosaic rendering requires numpy in the stream service environment.") from exc
    return np


class AlignedSetRepository:
    def __init__(
        self,
        camera_ids: list[str],
        recent_sets: int,
        preview_max_width: int = 1280,
        preview_max_height: int = 720,
        preview_jpeg_quality: int = 72,
    ) -> None:
        self._camera_ids = camera_ids
        self._recent_sets = max(recent_sets, 1)
        self._preview_max_width = max(preview_max_width, 320)
        self._preview_max_height = max(preview_max_height, 240)
        self._preview_jpeg_quality = min(max(preview_jpeg_quality, 30), 95)
        self._lock = threading.Lock()
        self._sets: OrderedDict[int, AlignedFrameSet] = OrderedDict()
        self._latest_sync: dict[str, Any] = {}
        self._latest_cameras: dict[str, Any] = {}
        self._last_error: str | None = None
        self._recording: dict[str, Any] = {
            "enabled": False,
            "active": False,
            "failed": False,
            "overflow_policy": None,
            "queue_maxsize": None,
            "queue_size": 0,
            "queue_high_watermark": 0,
            "submitted_sets": 0,
            "written_sets": 0,
            "dropped_sets": 0,
            "queue_full_events": 0,
            "first_failure_at_set": None,
            "last_error": None,
        }
        self._started_at = time.time()
        self._last_publish_at: float | None = None
        self._published_sets = 0
        self._running = True
        self._latest_preview_jpeg: bytes | None = None
        self._latest_preview_headers: dict[str, str] = {}
        self._last_preview_error: str | None = None
        self._preview_encoded_frames = 0
        self._preview_encode_total_ms = 0.0
        self._preview_encode_max_ms = 0.0
        self._preview_last_encode_ms: float | None = None
        self._preview_last_size_bytes: int | None = None
        self._publish_timestamps_s: deque[float] = deque()

    def publish(self, aligned_set: AlignedFrameSet, sync_snapshot: dict[str, object], camera_snapshot: dict[str, object]) -> None:
        preview_jpeg: bytes | None = None
        preview_headers: dict[str, str] = {}
        preview_error: str | None = None
        preview_encode_ms: float | None = None
        try:
            preview_started_at = time.perf_counter()
            preview_jpeg = build_preview_frame_as_jpeg(
                aligned_set,
                self._camera_ids,
                sync_snapshot,
                max_width=self._preview_max_width,
                max_height=self._preview_max_height,
                jpeg_quality=self._preview_jpeg_quality,
            )
            preview_encode_ms = (time.perf_counter() - preview_started_at) * 1000.0
            preview_headers = {
                "X-SensorProto-Set-Id": str(aligned_set.set_id),
                "X-SensorProto-Reference-Timestamp-S": f"{aligned_set.reference_timestamp_s:.6f}",
                "X-SensorProto-Skew-Ms": f"{aligned_set.skew_ms:.6f}",
                "X-SensorProto-Camera-Count": str(len(aligned_set.frames)),
            }
        except ValueError as exc:
            preview_jpeg = None
            preview_headers = {}
            preview_error = str(exc)

        with self._lock:
            now_s = time.time()
            self._sets[aligned_set.set_id] = aligned_set
            while len(self._sets) > self._recent_sets:
                self._sets.popitem(last=False)
            self._latest_sync = sync_snapshot
            self._latest_cameras = camera_snapshot
            if preview_jpeg is not None:
                self._latest_preview_jpeg = preview_jpeg
                self._latest_preview_headers = preview_headers
                self._last_preview_error = None
                self._preview_encoded_frames += 1
                if preview_encode_ms is not None:
                    self._preview_last_encode_ms = preview_encode_ms
                    self._preview_encode_total_ms += preview_encode_ms
                    self._preview_encode_max_ms = max(self._preview_encode_max_ms, preview_encode_ms)
                self._preview_last_size_bytes = len(preview_jpeg)
            elif preview_error is not None:
                self._last_preview_error = preview_error
            self._last_publish_at = now_s
            self._published_sets += 1
            self._publish_timestamps_s.append(now_s)
            self._trim_publish_history(now_s)

    def set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message

    def set_recording_status(self, payload: dict[str, object]) -> None:
        with self._lock:
            self._recording = dict(payload)

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def latest_payload(self) -> dict[str, object] | None:
        with self._lock:
            if not self._sets:
                return None
            _, aligned_set = next(reversed(self._sets.items()))
            payload = aligned_set.as_dict()
            payload["camera_order"] = self._camera_ids
            payload["published_sets"] = self._published_sets
            payload["sync"] = self._latest_sync
            payload["cameras"] = self._latest_cameras
            payload["server_time_s"] = round(time.time(), 3)
            return payload

    def health_payload(self) -> dict[str, object]:
        with self._lock:
            latest_set_id = next(reversed(self._sets.keys())) if self._sets else None
            now_s = time.time()
            self._trim_publish_history(now_s)
            return {
                "running": self._running,
                "camera_ids": self._camera_ids,
                "latest_set_id": latest_set_id,
                "published_sets": self._published_sets,
                "started_at_s": round(self._started_at, 3),
                "last_publish_at_s": round(self._last_publish_at, 3) if self._last_publish_at is not None else None,
                "last_error": self._last_error,
                "preview": {
                    "available": self._latest_preview_jpeg is not None,
                    "last_error": self._last_preview_error,
                    "max_width": self._preview_max_width,
                    "max_height": self._preview_max_height,
                    "jpeg_quality": self._preview_jpeg_quality,
                    "last_size_bytes": self._preview_last_size_bytes,
                    "encoded_frames": self._preview_encoded_frames,
                    "last_encode_ms": round(self._preview_last_encode_ms, 3) if self._preview_last_encode_ms is not None else None,
                    "avg_encode_ms": (
                        round(self._preview_encode_total_ms / self._preview_encoded_frames, 3)
                        if self._preview_encoded_frames
                        else None
                    ),
                    "max_encode_ms": round(self._preview_encode_max_ms, 3) if self._preview_encoded_frames else None,
                    "publish_rate_hz": round(self._compute_publish_rate_hz(now_s), 3),
                },
                "recording": dict(self._recording),
                "sync": self._latest_sync,
            }

    def get_frame_bmp(self, set_id: int, camera_id: str) -> bytes:
        with self._lock:
            aligned_set = self._sets.get(set_id)
            if aligned_set is None:
                raise KeyError(f"Unknown set id: {set_id}")
            frame = aligned_set.frames.get(camera_id)
            if frame is None:
                raise KeyError(f"Unknown camera id {camera_id} in set {set_id}")
        return encode_bgr_frame_as_bmp(frame)

    def get_latest_preview_jpeg(self) -> tuple[bytes, dict[str, str]]:
        with self._lock:
            if self._latest_preview_jpeg is None:
                raise LookupError("No preview frame available yet.")
            return self._latest_preview_jpeg, dict(self._latest_preview_headers)

    def _trim_publish_history(self, now_s: float) -> None:
        window_s = 5.0
        while self._publish_timestamps_s and now_s - self._publish_timestamps_s[0] > window_s:
            self._publish_timestamps_s.popleft()

    def _compute_publish_rate_hz(self, now_s: float) -> float:
        if len(self._publish_timestamps_s) < 2:
            return 0.0
        oldest_s = self._publish_timestamps_s[0]
        span_s = max(now_s - oldest_s, 0.001)
        return len(self._publish_timestamps_s) / span_s


def build_dashboard_html(title: str, refresh_ms: int) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #09111a;
      --panel: #102030;
      --text: #ecf2f8;
      --muted: #9fb1c4;
      --accent: #53d1c9;
      --warn: #ffd166;
    }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background: radial-gradient(circle at top, #17314a, var(--bg) 60%);
      color: var(--text);
    }}
    header {{
      padding: 20px 24px 8px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
    }}
    #summary {{
      color: var(--muted);
      font-size: 14px;
    }}
    main {{
      padding: 16px 24px 24px;
    }}
    .panel {{
      background: rgba(16, 32, 48, 0.9);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.25);
      padding: 14px;
    }}
    img {{
      display: block;
      width: 100%;
      background: #000;
      object-fit: contain;
      border-radius: 12px;
    }}
    .pill {{
      color: var(--accent);
      font-size: 12px;
    }}
    .warn {{
      color: var(--warn);
    }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <div id="summary">等待首个 preview mosaic...</div>
  </header>
  <main>
    <section class="panel">
      <div class="pill">latest-only preview</div>
      <img id="preview" alt="Latest preview mosaic">
    </section>
  </main>
  <script>
    const refreshMs = {refresh_ms};
    const preview = document.getElementById("preview");
    const summary = document.getElementById("summary");
    preview.addEventListener("load", () => {{
      summary.textContent = `preview refreshed at ${{new Date().toLocaleTimeString()}}`;
    }});
    preview.addEventListener("error", () => {{
      summary.textContent = "同步服务运行中，但尚未生成 preview。";
    }});

    function refresh() {{
      preview.src = `/api/preview.jpg?ts=${{Date.now()}}`;
    }}

    setInterval(refresh, refreshMs);
    refresh();
  </script>
</body>
</html>
"""


class StreamRequestHandler(BaseHTTPRequestHandler):
    server_version = "SensorProtoStream/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            self._send_html(self.server.dashboard_html)
            return
        if path == "/api/health":
            self._send_json(self.server.repository.health_payload())
            return
        if path == "/api/latest-set":
            payload = self.server.repository.latest_payload()
            if payload is None:
                self._send_json({"error": "No aligned frame set available yet."}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._send_json(payload)
            return
        if path == "/api/preview.jpg":
            try:
                payload, headers = self.server.repository.get_latest_preview_jpeg()
            except LookupError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._send_bytes(payload, "image/jpeg", extra_headers=headers)
            return
        if path.startswith("/api/sets/") and path.endswith(".bmp"):
            parts = path.strip("/").split("/")
            if len(parts) != 5 or parts[0] != "api" or parts[1] != "sets" or parts[3] != "frames":
                self._send_json({"error": "Malformed frame path."}, HTTPStatus.BAD_REQUEST)
                return
            try:
                set_id = int(parts[2])
            except ValueError:
                self._send_json({"error": "Invalid set id."}, HTTPStatus.BAD_REQUEST)
                return
            camera_id = parts[4].removesuffix(".bmp")
            try:
                payload = self.server.repository.get_frame_bmp(set_id, camera_id)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
                return
            self._send_bytes(payload, "image/bmp")
            return
        self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def _send_html(self, body: str) -> None:
        self._send_bytes(body.encode("utf-8"), "text/html; charset=utf-8")

    def _send_bytes(
        self,
        payload: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)


class StreamHttpServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address, repository: AlignedSetRepository, dashboard_html: str) -> None:
        super().__init__(server_address, StreamRequestHandler)
        self.repository = repository
        self.dashboard_html = dashboard_html

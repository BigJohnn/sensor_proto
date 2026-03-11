from __future__ import annotations

import json
import struct
import threading
import time
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from sensor_proto.models import AlignedFrameSet, Frame


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


class AlignedSetRepository:
    def __init__(self, camera_ids: list[str], recent_sets: int) -> None:
        self._camera_ids = camera_ids
        self._recent_sets = max(recent_sets, 1)
        self._lock = threading.Lock()
        self._sets: OrderedDict[int, AlignedFrameSet] = OrderedDict()
        self._latest_sync: dict[str, Any] = {}
        self._latest_cameras: dict[str, Any] = {}
        self._last_error: str | None = None
        self._started_at = time.time()
        self._last_publish_at: float | None = None
        self._published_sets = 0
        self._running = True

    def publish(self, aligned_set: AlignedFrameSet, sync_snapshot: dict[str, object], camera_snapshot: dict[str, object]) -> None:
        with self._lock:
            self._sets[aligned_set.set_id] = aligned_set
            while len(self._sets) > self._recent_sets:
                self._sets.popitem(last=False)
            self._latest_sync = sync_snapshot
            self._latest_cameras = camera_snapshot
            self._last_publish_at = time.time()
            self._published_sets += 1

    def set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message

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
            return {
                "running": self._running,
                "camera_ids": self._camera_ids,
                "latest_set_id": latest_set_id,
                "published_sets": self._published_sets,
                "started_at_s": round(self._started_at, 3),
                "last_publish_at_s": round(self._last_publish_at, 3) if self._last_publish_at is not None else None,
                "last_error": self._last_error,
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
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 14px;
      padding: 16px 24px 24px;
    }}
    .card {{
      background: rgba(16, 32, 48, 0.9);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.25);
    }}
    .card header {{
      padding: 12px 14px 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .meta {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
      padding: 0 14px 12px;
    }}
    img {{
      display: block;
      width: 100%;
      background: #000;
      aspect-ratio: 4 / 3;
      object-fit: contain;
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
    <div id="summary">等待首个同步帧集...</div>
  </header>
  <main id="grid"></main>
  <script>
    const refreshMs = {refresh_ms};
    const grid = document.getElementById("grid");
    const summary = document.getElementById("summary");
    let latestSetId = null;
    const cards = new Map();

    function ensureCard(cameraId) {{
      if (cards.has(cameraId)) {{
        return cards.get(cameraId);
      }}
      const card = document.createElement("section");
      card.className = "card";
      card.innerHTML = `
        <header>
          <strong>${{cameraId}}</strong>
          <span class="pill">等待数据</span>
        </header>
        <img alt="${{cameraId}}">
        <div class="meta"></div>
      `;
      grid.appendChild(card);
      cards.set(cameraId, card);
      return card;
    }}

    async function refresh() {{
      try {{
        const response = await fetch("/api/latest-set", {{ cache: "no-store" }});
        if (!response.ok) {{
          summary.textContent = "同步服务运行中，但尚未产生对齐帧集。";
          return;
        }}
        const payload = await response.json();
        summary.textContent =
          `set=${{payload.set_id}} | aligned_sets=${{payload.sync.aligned_sets}} | dropped=${{payload.sync.dropped_frames}} | skew=${{payload.skew_ms.toFixed(3)}}ms | warnings=${{payload.sync.warnings.length}}`;
        if (latestSetId === payload.set_id) {{
          return;
        }}
        latestSetId = payload.set_id;
        for (const cameraId of payload.camera_order) {{
          const frame = payload.frames[cameraId];
          const card = ensureCard(cameraId);
          const pill = card.querySelector(".pill");
          const meta = card.querySelector(".meta");
          const img = card.querySelector("img");
          const warningCodes = payload.sync.warnings
            .filter((item) => item.camera_id === cameraId)
            .map((item) => item.code)
            .join(", ");
          pill.textContent = `offset=${{payload.offsets_ms[cameraId].toFixed(3)}}ms`;
          pill.className = warningCodes ? "pill warn" : "pill";
          meta.textContent =
            `serial=${{frame.sensor_serial}} | frame=${{frame.frame_counter}} | seq=${{frame.sequence}} | ts=${{frame.device_timestamp_ms}} | domain=${{frame.timestamp_domain}}${{warningCodes ? " | warn=" + warningCodes : ""}}`;
          img.src = `/api/sets/${{payload.set_id}}/frames/${{cameraId}}.bmp?ts=${{Date.now()}}`;
        }}
      }} catch (error) {{
        summary.textContent = `获取同步数据失败: ${{error}}`;
      }}
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

    def _send_bytes(self, payload: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


class StreamHttpServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address, repository: AlignedSetRepository, dashboard_html: str) -> None:
        super().__init__(server_address, StreamRequestHandler)
        self.repository = repository
        self.dashboard_html = dashboard_html

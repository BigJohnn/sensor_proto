from __future__ import annotations

import argparse
import time

from sensor_proto.preview import GridLayout, compute_grid_dimensions, compute_grid_layout
from sensor_proto.stream_client import (
    AlignedFrameBundle,
    AlignedStreamClient,
    StreamClientError,
    ZmqAlignedStreamClient,
    resolve_zmq_endpoint,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Display the latest aligned multi-camera stream in an OpenCV window.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787", help="Base URL of the stream service.")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--transport",
        choices=("auto", "http", "zmq"),
        default="auto",
        help="Viewer data-plane transport to use.",
    )
    parser.add_argument(
        "--zmq-endpoint",
        default=None,
        help="Explicit ZMQ endpoint, e.g. tcp://127.0.0.1:5555. Required for zmq mode if HTTP health is unavailable.",
    )
    parser.add_argument("--max-width", type=int, default=1600, help="Maximum viewer window width in pixels.")
    parser.add_argument("--max-height", type=int, default=900, help="Maximum viewer window height in pixels.")
    parser.add_argument("--poll-interval-ms", type=int, default=60, help="Delay between fetch attempts in milliseconds.")
    parser.add_argument(
        "--stale-after-ms",
        type=int,
        default=1500,
        help="Warn when the latest aligned set does not change for this long.",
    )
    parser.add_argument("--window-name", default="SensorProto Multi-Camera Viewer", help="OpenCV window title.")
    return parser.parse_args()


def render_aligned_grid(
    aligned: AlignedFrameBundle,
    max_width: int,
    max_height: int,
    gap_px: int = 12,
    header_px: int = 72,
):
    cv2 = _load_cv2_module()
    np = _load_numpy_module()

    first_frame = aligned.frames[aligned.camera_order[0]]
    frame_height, frame_width = first_frame.shape[:2]
    layout = compute_grid_layout(
        frame_width=frame_width,
        frame_height=frame_height,
        camera_count=len(aligned.camera_order),
        max_width=max_width,
        max_height=max_height,
        gap_px=gap_px,
        header_px=header_px,
    )
    canvas = np.zeros((layout.canvas_height, layout.canvas_width, 3), dtype=np.uint8)
    canvas[:] = (9, 17, 26)
    summary = (
        f"set={aligned.set_id}  ts={aligned.timestamp:.3f}  "
        f"skew={aligned.skew_ms:.3f}ms  cams={len(aligned.camera_order)}"
    )
    cv2.putText(canvas, summary, (gap_px, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (236, 242, 248), 2, cv2.LINE_AA)
    cv2.putText(canvas, "press q or ESC to exit", (gap_px, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (159, 177, 196), 1, cv2.LINE_AA)

    for index, camera_id in enumerate(aligned.camera_order):
        row = index // layout.cols
        col = index % layout.cols
        x = gap_px + col * (layout.cell_width + gap_px)
        y = header_px + gap_px + row * (layout.cell_height + gap_px)
        frame = aligned.frames[camera_id]
        resized = cv2.resize(frame, (layout.cell_width, layout.cell_height), interpolation=cv2.INTER_AREA)
        canvas[y : y + layout.cell_height, x : x + layout.cell_width] = resized
        cv2.rectangle(canvas, (x, y), (x + layout.cell_width, y + layout.cell_height), (83, 209, 201), 1)
        offset_ms = aligned.offsets_ms.get(camera_id, 0.0)
        label = f"{camera_id}  offset={offset_ms:.2f}ms"
        cv2.putText(canvas, label, (x + 8, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 209, 102), 2, cv2.LINE_AA)

    return canvas, layout


def compute_stalled_duration_s(
    last_set_change_at: float | None,
    now_monotonic: float,
    stale_after_ms: int,
) -> float | None:
    if last_set_change_at is None:
        return None
    stale_after_s = max(0.0, stale_after_ms / 1000.0)
    stalled_for_s = max(0.0, now_monotonic - last_set_change_at)
    if stalled_for_s < stale_after_s:
        return None
    return stalled_for_s


def build_stalled_message(last_set_id: int | None, stalled_for_s: float) -> str:
    if last_set_id is None:
        return f"stream stalled for {stalled_for_s:.1f}s"
    return f"stream stalled for {stalled_for_s:.1f}s on set={last_set_id}"


def draw_status_banner(canvas, message: str, color: tuple[int, int, int] = (45, 45, 160)) -> None:
    cv2 = _load_cv2_module()
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 38), color, -1)
    cv2.putText(canvas, message, (16, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (245, 247, 250), 2, cv2.LINE_AA)


def resolve_viewer_transport_mode(
    *,
    base_url: str,
    timeout_s: float,
    transport: str,
    zmq_endpoint: str | None,
) -> tuple[str, str | None]:
    if transport == "http":
        return "http", None
    http_client = AlignedStreamClient(base_url, timeout_s=timeout_s)
    if transport == "zmq":
        endpoint = zmq_endpoint
        if endpoint is None:
            endpoint = resolve_zmq_endpoint(base_url, http_client.get_health())
        return "zmq", endpoint
    health = http_client.get_health()
    transport_payload = health.get("transport", {})
    if isinstance(transport_payload, dict) and transport_payload.get("enabled") and transport_payload.get("kind") == "zmq":
        return "zmq", resolve_zmq_endpoint(base_url, health, explicit_endpoint=zmq_endpoint)
    return "http", None


def _load_cv2_module():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on host environment
        raise StreamClientError("The realtime viewer requires cv2 in the host environment.") from exc
    return cv2


def _load_numpy_module():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on host environment
        raise StreamClientError("The realtime viewer requires numpy in the host environment.") from exc
    return np


def main() -> None:
    args = parse_args()
    client = AlignedStreamClient(args.base_url, timeout_s=args.timeout_s)
    viewer_transport, viewer_zmq_endpoint = resolve_viewer_transport_mode(
        base_url=args.base_url,
        timeout_s=args.timeout_s,
        transport=args.transport,
        zmq_endpoint=args.zmq_endpoint,
    )
    zmq_client = (
        ZmqAlignedStreamClient(viewer_zmq_endpoint, timeout_ms=max(1, int(args.timeout_s * 1000.0)))
        if viewer_transport == "zmq" and viewer_zmq_endpoint is not None
        else None
    )
    cv2 = _load_cv2_module()

    cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(args.window_name, args.max_width, args.max_height)

    last_set_id: int | None = None
    last_canvas = None
    last_set_change_at: float | None = None
    while True:
        overlay_message: str | None = None
        overlay_color = (45, 45, 160)
        try:
            if zmq_client is not None:
                aligned = zmq_client.recv_aligned_set(timeout_ms=max(1, args.poll_interval_ms))
                if aligned.set_id != last_set_id:
                    last_canvas, layout = render_aligned_grid(aligned, args.max_width, args.max_height)
                    cv2.resizeWindow(
                        args.window_name,
                        min(args.max_width, layout.canvas_width),
                        min(args.max_height, layout.canvas_height),
                    )
                    last_set_id = aligned.set_id
                    last_set_change_at = time.monotonic()
            else:
                preview = client.get_latest_preview()
                if preview.set_id != last_set_id:
                    last_canvas = preview.frame
                    frame_height, frame_width = last_canvas.shape[:2]
                    cv2.resizeWindow(args.window_name, min(args.max_width, frame_width), min(args.max_height, frame_height))
                    last_set_id = preview.set_id
                    last_set_change_at = time.monotonic()
            stalled_for_s = compute_stalled_duration_s(last_set_change_at, time.monotonic(), args.stale_after_ms)
            if stalled_for_s is not None:
                overlay_message = build_stalled_message(last_set_id, stalled_for_s)
                overlay_color = (31, 95, 176)
        except StreamClientError as exc:
            if last_canvas is None:
                last_canvas = _render_error_canvas(str(exc), args.max_width, args.max_height)
                last_set_change_at = None
            else:
                overlay_message = str(exc)

        if last_canvas is not None:
            display_canvas = last_canvas.copy()
            if overlay_message:
                draw_status_banner(display_canvas, overlay_message, color=overlay_color)
            cv2.imshow(args.window_name, display_canvas)
        key = cv2.waitKey(max(1, args.poll_interval_ms)) & 0xFF
        if key in (27, ord("q")):
            break

    if zmq_client is not None:
        zmq_client.close()
    cv2.destroyAllWindows()


def _render_error_canvas(message: str, max_width: int, max_height: int):
    cv2 = _load_cv2_module()
    np = _load_numpy_module()
    width = max(640, min(max_width, 1280))
    height = max(180, min(max_height, 240))
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:] = (24, 18, 18)
    cv2.putText(canvas, "Stream viewer waiting for frames", (24, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 214, 102), 2, cv2.LINE_AA)
    cv2.putText(canvas, message[: max(20, width // 10)], (24, 104), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (236, 242, 248), 1, cv2.LINE_AA)
    cv2.putText(canvas, "press q or ESC to exit", (24, 148), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (159, 177, 196), 1, cv2.LINE_AA)
    return canvas


if __name__ == "__main__":
    main()

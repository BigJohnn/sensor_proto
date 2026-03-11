from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass

from sensor_proto.stream_client import AlignedFrameBundle, AlignedStreamClient, StreamClientError


@dataclass(slots=True)
class GridLayout:
    rows: int
    cols: int
    cell_width: int
    cell_height: int
    canvas_width: int
    canvas_height: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Display the latest aligned multi-camera stream in an OpenCV window.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787", help="Base URL of the stream service.")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="HTTP timeout in seconds.")
    parser.add_argument("--max-width", type=int, default=1600, help="Maximum viewer window width in pixels.")
    parser.add_argument("--max-height", type=int, default=900, help="Maximum viewer window height in pixels.")
    parser.add_argument("--poll-interval-ms", type=int, default=60, help="Delay between fetch attempts in milliseconds.")
    parser.add_argument("--window-name", default="SensorProto Multi-Camera Viewer", help="OpenCV window title.")
    return parser.parse_args()


def compute_grid_dimensions(camera_count: int) -> tuple[int, int]:
    if camera_count <= 0:
        raise ValueError("camera_count must be positive.")
    cols = math.ceil(math.sqrt(camera_count))
    rows = math.ceil(camera_count / cols)
    return rows, cols


def compute_grid_layout(
    frame_width: int,
    frame_height: int,
    camera_count: int,
    max_width: int,
    max_height: int,
    gap_px: int = 12,
    header_px: int = 72,
) -> GridLayout:
    rows, cols = compute_grid_dimensions(camera_count)
    available_width = max(1, max_width - gap_px * (cols + 1))
    available_height = max(1, max_height - header_px - gap_px * (rows + 1))
    scale = min(available_width / (cols * frame_width), available_height / (rows * frame_height), 1.0)
    cell_width = max(1, int(frame_width * scale))
    cell_height = max(1, int(frame_height * scale))
    canvas_width = cell_width * cols + gap_px * (cols + 1)
    canvas_height = header_px + cell_height * rows + gap_px * (rows + 1)
    return GridLayout(
        rows=rows,
        cols=cols,
        cell_width=cell_width,
        cell_height=cell_height,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
    )


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
    cv2 = _load_cv2_module()

    cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(args.window_name, args.max_width, args.max_height)

    last_set_id: int | None = None
    last_canvas = None
    while True:
        try:
            aligned = client.get_latest_aligned_set()
            if aligned.set_id != last_set_id:
                last_canvas, layout = render_aligned_grid(aligned, args.max_width, args.max_height)
                cv2.resizeWindow(args.window_name, layout.canvas_width, layout.canvas_height)
                last_set_id = aligned.set_id
        except StreamClientError as exc:
            last_canvas = _render_error_canvas(str(exc), args.max_width, args.max_height)

        if last_canvas is not None:
            cv2.imshow(args.window_name, last_canvas)
        key = cv2.waitKey(max(1, args.poll_interval_ms)) & 0xFF
        if key in (27, ord("q")):
            break
        time.sleep(max(0.0, args.poll_interval_ms / 1000.0))

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

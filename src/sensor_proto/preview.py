from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class GridLayout:
    rows: int
    cols: int
    cell_width: int
    cell_height: int
    canvas_width: int
    canvas_height: int


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

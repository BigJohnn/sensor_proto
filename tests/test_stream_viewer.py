from __future__ import annotations

import unittest

from sensor_proto.stream_viewer import compute_grid_dimensions, compute_grid_layout


class StreamViewerTests(unittest.TestCase):
    def test_compute_grid_dimensions_balances_rows_and_columns(self) -> None:
        self.assertEqual(compute_grid_dimensions(1), (1, 1))
        self.assertEqual(compute_grid_dimensions(4), (2, 2))
        self.assertEqual(compute_grid_dimensions(7), (3, 3))
        self.assertEqual(compute_grid_dimensions(8), (3, 3))

    def test_compute_grid_layout_scales_cells_to_fit_screen(self) -> None:
        layout = compute_grid_layout(
            frame_width=640,
            frame_height=480,
            camera_count=8,
            max_width=1600,
            max_height=900,
        )

        self.assertEqual(layout.rows, 3)
        self.assertEqual(layout.cols, 3)
        self.assertLessEqual(layout.canvas_width, 1600)
        self.assertLessEqual(layout.canvas_height, 900)
        self.assertGreater(layout.cell_width, 0)
        self.assertGreater(layout.cell_height, 0)


if __name__ == "__main__":
    unittest.main()

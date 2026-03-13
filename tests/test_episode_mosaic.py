from __future__ import annotations

import unittest

from sensor_proto.episode_mosaic import GridLayout, build_filter_complex, choose_grid_layout


class EpisodeMosaicTests(unittest.TestCase):
    def test_choose_grid_layout_prefers_compact_wide_layout_without_empty_tiles(self) -> None:
        layout = choose_grid_layout(8, tile_width=640, tile_height=480)

        self.assertEqual(layout.columns, 4)
        self.assertEqual(layout.rows, 2)
        self.assertEqual(layout.tile_width, 640)
        self.assertEqual(layout.tile_height, 480)

    def test_choose_grid_layout_respects_explicit_columns(self) -> None:
        layout = choose_grid_layout(5, columns=3, tile_width=320, tile_height=240)

        self.assertEqual(layout.columns, 3)
        self.assertEqual(layout.rows, 2)

    def test_build_filter_complex_uses_row_major_tile_positions(self) -> None:
        filter_complex = build_filter_complex(
            4,
            GridLayout(columns=2, rows=2, tile_width=640, tile_height=480),
        )

        self.assertIn("scale=640:480", filter_complex)
        self.assertIn("pad=640:480", filter_complex)
        self.assertIn("xstack=inputs=4:layout=0_0|640_0|0_480|640_480:fill=black[vout]", filter_complex)


if __name__ == "__main__":
    unittest.main()

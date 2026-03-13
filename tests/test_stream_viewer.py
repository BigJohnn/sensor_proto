from __future__ import annotations

import unittest
from unittest.mock import patch

from sensor_proto.stream_viewer import (
    build_stalled_message,
    compute_grid_dimensions,
    compute_grid_layout,
    compute_stalled_duration_s,
    resolve_viewer_transport_mode,
)


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

    def test_compute_stalled_duration_s_returns_none_before_threshold(self) -> None:
        stalled_for_s = compute_stalled_duration_s(last_set_change_at=10.0, now_monotonic=11.2, stale_after_ms=1500)
        self.assertIsNone(stalled_for_s)

    def test_compute_stalled_duration_s_returns_elapsed_time_after_threshold(self) -> None:
        stalled_for_s = compute_stalled_duration_s(last_set_change_at=10.0, now_monotonic=11.6, stale_after_ms=1500)
        self.assertAlmostEqual(stalled_for_s, 1.6)

    def test_build_stalled_message_includes_set_id_when_available(self) -> None:
        self.assertEqual(build_stalled_message(42, 2.4), "stream stalled for 2.4s on set=42")

    def test_resolve_viewer_transport_mode_auto_prefers_zmq(self) -> None:
        with patch("sensor_proto.stream_viewer.AlignedStreamClient") as http_client_cls:
            http_client = http_client_cls.return_value
            http_client.get_health.return_value = {"transport": {"enabled": True, "kind": "zmq", "port": 5555}}

            mode, endpoint = resolve_viewer_transport_mode(
                base_url="http://127.0.0.1:8787",
                timeout_s=2.0,
                transport="auto",
                zmq_endpoint=None,
            )

        self.assertEqual(mode, "zmq")
        self.assertEqual(endpoint, "tcp://127.0.0.1:5555")

    def test_resolve_viewer_transport_mode_http_keeps_preview_path(self) -> None:
        mode, endpoint = resolve_viewer_transport_mode(
            base_url="http://127.0.0.1:8787",
            timeout_s=2.0,
            transport="http",
            zmq_endpoint=None,
        )

        self.assertEqual(mode, "http")
        self.assertIsNone(endpoint)


if __name__ == "__main__":
    unittest.main()

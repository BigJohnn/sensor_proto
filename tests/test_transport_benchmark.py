from __future__ import annotations

import unittest
from unittest import mock

from sensor_proto.transport_benchmark import compute_latency_ms, uses_epoch_clock


class TransportBenchmarkTests(unittest.TestCase):
    def test_uses_epoch_clock_for_wall_clock_reference_timestamp(self) -> None:
        self.assertTrue(uses_epoch_clock(1_773_371_611.296))

    def test_uses_monotonic_clock_for_mock_reference_timestamp(self) -> None:
        self.assertFalse(uses_epoch_clock(123_456.789))

    def test_compute_latency_ms_uses_time_time_for_epoch_reference_timestamp(self) -> None:
        with mock.patch("sensor_proto.transport_benchmark.time.time", return_value=1_700_000_000.125):
            self.assertAlmostEqual(compute_latency_ms(1_700_000_000.0), 125.0)

    def test_compute_latency_ms_uses_time_monotonic_for_monotonic_reference_timestamp(self) -> None:
        with mock.patch("sensor_proto.transport_benchmark.time.monotonic", return_value=50.125):
            self.assertAlmostEqual(compute_latency_ms(50.0), 125.0)


if __name__ == "__main__":
    unittest.main()

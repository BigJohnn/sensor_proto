from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any

from sensor_proto.stream_client import AlignedStreamClient, StreamClientError, ZmqAlignedStreamClient, resolve_zmq_endpoint


EPOCH_THRESHOLD_S = 946684800.0  # 2000-01-01T00:00:00Z


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark sensor_proto aligned-set transports against a running stream service.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787", help="HTTP base URL for health and HTTP transport.")
    parser.add_argument(
        "--transport",
        choices=("http", "zmq"),
        required=True,
        help="Aligned-set transport to benchmark.",
    )
    parser.add_argument("--zmq-endpoint", default=None, help="Explicit ZMQ endpoint, e.g. tcp://127.0.0.1:5555.")
    parser.add_argument("--count", type=int, default=40, help="Number of unique aligned sets to receive.")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="HTTP timeout or per-receive timeout in seconds.")
    parser.add_argument("--max-wait-s", type=float, default=20.0, help="Maximum wall time allowed for the benchmark run.")
    parser.add_argument(
        "--poll-sleep-ms",
        type=int,
        default=5,
        help="Sleep between duplicate HTTP latest-set polls to avoid tight spin loops.",
    )
    return parser.parse_args()


def benchmark_http(
    client: AlignedStreamClient,
    *,
    count: int,
    max_wait_s: float,
    poll_sleep_ms: int,
) -> dict[str, Any]:
    started_at = time.monotonic()
    deadline = started_at + max_wait_s
    unique_sets = 0
    duplicate_polls = 0
    last_set_id: int | None = None
    latencies_ms: list[float] = []
    first_set_id: int | None = None
    last_observed_set_id: int | None = None

    while unique_sets < count:
        if time.monotonic() > deadline:
            raise StreamClientError(f"HTTP benchmark timed out after collecting {unique_sets}/{count} unique aligned sets.")
        aligned = client.get_latest_aligned_set()
        last_observed_set_id = aligned.set_id
        if first_set_id is None:
            first_set_id = aligned.set_id
        if aligned.set_id == last_set_id:
            duplicate_polls += 1
            time.sleep(max(0, poll_sleep_ms) / 1000.0)
            continue
        last_set_id = aligned.set_id
        unique_sets += 1
        latencies_ms.append(compute_latency_ms(aligned.timestamp))

    duration_s = max(time.monotonic() - started_at, 1e-9)
    return build_result_payload(
        transport="http",
        count=count,
        duration_s=duration_s,
        latencies_ms=latencies_ms,
        extra={
            "duplicate_polls": duplicate_polls,
            "first_set_id": first_set_id,
            "last_set_id": last_observed_set_id,
        },
    )


def benchmark_zmq(
    client: ZmqAlignedStreamClient,
    *,
    count: int,
    timeout_s: float,
) -> dict[str, Any]:
    started_at = time.monotonic()
    latencies_ms: list[float] = []
    first_set_id: int | None = None
    last_set_id: int | None = None
    for _ in range(count):
        aligned = client.recv_aligned_set(timeout_ms=max(1, int(timeout_s * 1000.0)))
        if first_set_id is None:
            first_set_id = aligned.set_id
        last_set_id = aligned.set_id
        latencies_ms.append(compute_latency_ms(aligned.timestamp))
    duration_s = max(time.monotonic() - started_at, 1e-9)
    return build_result_payload(
        transport="zmq",
        count=count,
        duration_s=duration_s,
        latencies_ms=latencies_ms,
        extra={
            "first_set_id": first_set_id,
            "last_set_id": last_set_id,
        },
    )


def build_result_payload(
    *,
    transport: str,
    count: int,
    duration_s: float,
    latencies_ms: list[float],
    extra: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "transport": transport,
        "count": count,
        "duration_s": round(duration_s, 6),
        "throughput_hz": round(count / duration_s, 3),
        "latency_ms": {
            "avg": round(statistics.fmean(latencies_ms), 3) if latencies_ms else None,
            "median": round(statistics.median(latencies_ms), 3) if latencies_ms else None,
            "max": round(max(latencies_ms), 3) if latencies_ms else None,
        },
    }
    payload.update(extra)
    return payload


def compute_latency_ms(reference_timestamp_s: float) -> float:
    now_s = time.time() if uses_epoch_clock(reference_timestamp_s) else time.monotonic()
    return (now_s - reference_timestamp_s) * 1000.0


def uses_epoch_clock(reference_timestamp_s: float) -> bool:
    return reference_timestamp_s >= EPOCH_THRESHOLD_S


def main() -> None:
    args = parse_args()
    http_client = AlignedStreamClient(args.base_url, timeout_s=args.timeout_s)
    if args.transport == "http":
        result = benchmark_http(
            http_client,
            count=args.count,
            max_wait_s=args.max_wait_s,
            poll_sleep_ms=args.poll_sleep_ms,
        )
    else:
        health = http_client.get_health()
        endpoint = resolve_zmq_endpoint(args.base_url, health, explicit_endpoint=args.zmq_endpoint)
        zmq_client = ZmqAlignedStreamClient(endpoint, timeout_ms=max(1, int(args.timeout_s * 1000.0)))
        try:
            result = benchmark_zmq(
                zmq_client,
                count=args.count,
                timeout_s=args.timeout_s,
            )
        finally:
            zmq_client.close()
    result["health"] = http_client.get_health()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

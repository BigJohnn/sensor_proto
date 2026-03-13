from __future__ import annotations

import argparse
import json
from pathlib import Path

from sensor_proto.stream_client import (
    AlignedFrameBundle,
    AlignedStreamClient,
    StreamClientError,
    ZmqAlignedStreamClient,
    resolve_zmq_endpoint,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch the latest aligned frame set from the stream service.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787", help="Base URL of the stream service.")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--transport",
        choices=("auto", "http", "zmq"),
        default="auto",
        help="Aligned-set data-plane transport to use.",
    )
    parser.add_argument(
        "--zmq-endpoint",
        default=None,
        help="Explicit ZMQ endpoint, e.g. tcp://127.0.0.1:5555. Required for zmq mode if HTTP health is unavailable.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional directory to save each aligned frame as PNG.",
    )
    return parser.parse_args()


def save_aligned_frames(aligned: AlignedFrameBundle, output_dir: str | Path) -> dict[str, str]:
    cv2 = _load_cv2_module()
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_files: dict[str, str] = {}
    for camera_id, frame in aligned.frames.items():
        output_path = target_dir / f"set-{aligned.set_id:06d}-{camera_id}.png"
        if not cv2.imwrite(str(output_path), frame):
            raise StreamClientError(f"Failed to write frame for {camera_id} to {output_path}")
        saved_files[camera_id] = str(output_path)
    return saved_files


def _load_cv2_module():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on host environment
        raise StreamClientError("Saving frames requires cv2 in the host environment.") from exc
    return cv2


def build_summary(aligned: AlignedFrameBundle, saved_files: dict[str, str] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "set_id": aligned.set_id,
        "timestamp": aligned.timestamp,
        "skew_ms": aligned.skew_ms,
        "camera_order": aligned.camera_order,
        "offsets_ms": aligned.offsets_ms,
        "device_timestamps_ms": aligned.device_timestamps_ms,
    }
    if saved_files:
        payload["saved_files"] = saved_files
    return payload


def load_aligned_set(
    *,
    base_url: str,
    timeout_s: float,
    transport: str,
    zmq_endpoint: str | None,
) -> AlignedFrameBundle:
    http_client = AlignedStreamClient(base_url, timeout_s=timeout_s)
    if transport == "http":
        return http_client.get_latest_aligned_set()
    if transport == "zmq":
        endpoint = zmq_endpoint
        if endpoint is None:
            endpoint = resolve_zmq_endpoint(base_url, http_client.get_health())
        client = ZmqAlignedStreamClient(endpoint, timeout_ms=max(1, int(timeout_s * 1000.0)))
        try:
            return client.recv_aligned_set()
        finally:
            client.close()

    health = http_client.get_health()
    transport_payload = health.get("transport", {})
    if isinstance(transport_payload, dict) and transport_payload.get("enabled") and transport_payload.get("kind") == "zmq":
        endpoint = resolve_zmq_endpoint(base_url, health, explicit_endpoint=zmq_endpoint)
        client = ZmqAlignedStreamClient(endpoint, timeout_ms=max(1, int(timeout_s * 1000.0)))
        try:
            return client.recv_aligned_set()
        finally:
            client.close()
    return http_client.get_latest_aligned_set()


def main() -> None:
    args = parse_args()
    aligned = load_aligned_set(
        base_url=args.base_url,
        timeout_s=args.timeout_s,
        transport=args.transport,
        zmq_endpoint=args.zmq_endpoint,
    )
    saved_files = save_aligned_frames(aligned, args.output_dir) if args.output_dir else None
    print(json.dumps(build_summary(aligned, saved_files), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

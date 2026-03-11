from __future__ import annotations

import argparse
import json
from pathlib import Path

from sensor_proto.stream_client import AlignedFrameBundle, AlignedStreamClient, StreamClientError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch the latest aligned frame set from the stream service.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787", help="Base URL of the stream service.")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="HTTP timeout in seconds.")
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


def main() -> None:
    args = parse_args()
    client = AlignedStreamClient(args.base_url, timeout_s=args.timeout_s)
    aligned = client.get_latest_aligned_set()
    saved_files = save_aligned_frames(aligned, args.output_dir) if args.output_dir else None
    print(json.dumps(build_summary(aligned, saved_files), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

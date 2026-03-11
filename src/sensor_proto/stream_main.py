from __future__ import annotations

import argparse
import asyncio
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sensor_proto.cameras.realsense_discovery import RealSenseDeviceInfo, discover_realsense_devices
from sensor_proto.config import load_run_config, load_run_config_payload, write_run_config_payload
from sensor_proto.stream_server import AlignedSetRepository, StreamHttpServer, build_dashboard_html
from sensor_proto.streaming import SynchronizedStreamRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run synchronized multi-camera stream server.")
    parser.add_argument("--config", required=True, help="Path to JSON template configuration.")
    parser.add_argument(
        "--generated-config",
        default="artifacts/realsense-stream-runtime.json",
        help="Path to write the auto-generated runtime configuration.",
    )
    parser.add_argument(
        "--expected-cameras",
        type=int,
        default=None,
        help="Expected number of connected RealSense cameras. Defaults to template camera count.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime_config_path = prepare_stream_runtime_config(
        template_path=args.config,
        generated_config_path=args.generated_config,
        expected_cameras=args.expected_cameras,
    )
    config = load_run_config(runtime_config_path)
    repository = AlignedSetRepository(
        camera_ids=[camera.id for camera in config.cameras],
        recent_sets=config.stream.recent_sets,
    )
    stop_requested = threading.Event()

    runner = SynchronizedStreamRunner(
        config,
        on_aligned_set=repository.publish,
        on_error=repository.set_error,
    )
    capture_thread = threading.Thread(
        target=lambda: asyncio.run(runner.run_until_stopped(stop_requested)),
        name="sync-stream-capture",
        daemon=True,
    )
    capture_thread.start()

    server = StreamHttpServer(
        (config.stream.host, config.stream.port),
        repository,
        build_dashboard_html(f"RealSense {len(config.cameras)}-Camera Sync Viewer", config.stream.client_refresh_ms),
    )
    print(f"Serving synchronized stream on http://{config.stream.host}:{config.stream.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_requested.set()
        repository.stop()
        server.server_close()
        capture_thread.join(timeout=10)


def prepare_stream_runtime_config(template_path: str, generated_config_path: str, expected_cameras: int | None = None) -> str:
    payload = load_run_config_payload(template_path)
    cameras = payload.get("cameras", [])
    if not isinstance(cameras, list) or not cameras:
        raise ValueError("Template config must define at least one camera.")
    if not all(isinstance(camera, dict) and camera.get("kind") == "realsense" for camera in cameras):
        return template_path

    devices = discover_realsense_devices()
    if not devices:
        raise RuntimeError("No RealSense cameras detected.")
    if expected_cameras is not None and len(devices) != expected_cameras:
        raise RuntimeError(
            f"Expected {expected_cameras} RealSense cameras, but detected {len(devices)}: "
            f"{', '.join(device.serial for device in devices) or 'none'}"
        )
    print(
        f"Detected {len(devices)} RealSense camera(s) from template with {len(cameras)} camera slot(s): "
        f"{', '.join(device.serial for device in devices)}"
    )

    generated_payload = build_realsense_stream_config_payload(payload, devices)
    generated_payload["generated_from"] = str(Path(template_path))
    write_run_config_payload(generated_config_path, generated_payload)
    print(f"Generated runtime config at {generated_config_path}")
    return generated_config_path


def build_realsense_stream_config_payload(
    template_payload: dict[str, Any],
    devices: list[RealSenseDeviceInfo],
) -> dict[str, Any]:
    template_cameras = template_payload.get("cameras", [])
    if not isinstance(template_cameras, list) or not template_cameras:
        raise ValueError("Template config must define at least one camera.")

    first_camera = template_cameras[0]
    if not isinstance(first_camera, dict):
        raise ValueError("Template camera entries must be JSON objects.")

    generated_cameras: list[dict[str, Any]] = []
    for index, device in enumerate(devices):
        generated_camera = {
            "id": f"rs-{index:02d}",
            "kind": "realsense",
            "model": device.model,
            "serial": device.serial,
            "fps": int(first_camera.get("fps", 30)),
            "width": int(first_camera.get("width", 640)),
            "height": int(first_camera.get("height", 480)),
            "capture_image_data": True,
        }
        if first_camera.get("max_frames") is not None:
            generated_camera["max_frames"] = int(first_camera["max_frames"])
        generated_cameras.append(generated_camera)

    generated_payload = dict(template_payload)
    generated_payload["duration_s"] = 0.0
    generated_payload["cameras"] = generated_cameras
    generated_payload.setdefault(
        "stream",
        {
            "host": "0.0.0.0",
            "port": 8787,
            "recent_sets": 4,
            "client_refresh_ms": 300,
        },
    )

    sync = dict(generated_payload.get("sync", {}))
    sync["reference_camera_id"] = generated_cameras[0]["id"]
    generated_payload["sync"] = sync
    generated_payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    generated_payload["device_inventory"] = [
        {
            "serial": device.serial,
            "name": device.name,
            "model": device.model,
            "physical_port": device.physical_port,
            "product_line": device.product_line,
            "usb_type": device.usb_type,
            "firmware_version": device.firmware_version,
        }
        for device in devices
    ]
    return generated_payload


if __name__ == "__main__":
    main()

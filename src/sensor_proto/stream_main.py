from __future__ import annotations

import argparse
import asyncio
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sensor_proto.cameras.hikrobot_discovery import HikrobotDeviceInfo, discover_hikrobot_devices
from sensor_proto.cameras.realsense_discovery import RealSenseDeviceInfo, discover_realsense_devices
from sensor_proto.config import load_run_config, load_run_config_payload, write_run_config_payload
from sensor_proto.recording import RecordingSink
from sensor_proto.streaming import SynchronizedStreamRunner
from sensor_proto.transport import AlignedSetEvent, CompositeAlignedSetSink, ZmqAlignedSetPublisher, ZmqAlignedSetSink, ZmqTransportConfig, build_http_stream_runtime


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
    parser.add_argument(
        "--stop-after-aligned-sets",
        type=int,
        default=None,
        help="Stop the stream after publishing this many aligned frame sets.",
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
    recording_sink = RecordingSink.from_config(config) if config.recording.enabled else None
    http_runtime = build_http_stream_runtime(config, recording_sink)
    repository = http_runtime.repository
    server = http_runtime.server
    recording_publish_sink = http_runtime.recording_publish_sink
    stop_requested = threading.Event()
    aligned_set_count = 0
    recording_failure_reported = False
    zmq_publish_sink: ZmqAlignedSetSink | None = None

    def request_shutdown(message: str, *, mark_error: bool = True) -> None:
        print(f"Stopping stream: {message}", flush=True)
        if mark_error:
            repository.set_error(message)
        stop_requested.set()
        server.shutdown()

    aligned_set_sinks = [http_runtime.aligned_set_sink]
    if config.transport.enabled:
        zmq_publish_sink = ZmqAlignedSetSink(
            ZmqAlignedSetPublisher(
                ZmqTransportConfig(
                    bind_host=config.transport.bind_host,
                    port=config.transport.port,
                    topic=config.transport.topic,
                    jpeg_quality=config.transport.jpeg_quality,
                    max_queue=config.transport.max_queue,
                    backpressure_strategy=config.transport.backpressure_strategy,
                )
            ),
            camera_order=[camera.id for camera in config.cameras],
            max_queue=config.transport.max_queue,
            backpressure_strategy=config.transport.backpressure_strategy,
            on_error=request_shutdown,
            on_status=lambda payload: repository.set_transport_status(
                {
                    "kind": "zmq",
                    "port": config.transport.port,
                    "topic": config.transport.topic,
                    **payload,
                }
            ),
        )
        aligned_set_sinks.append(zmq_publish_sink)
    else:
        repository.set_transport_status(
            {
                "enabled": False,
                "kind": None,
                "port": None,
                "topic": None,
                "active": False,
                "failed": False,
                "backpressure_strategy": None,
                "queue_maxsize": None,
                "queue_size": 0,
                "submitted_sets": 0,
                "published_sets": 0,
                "dropped_sets": 0,
                "would_block_events": 0,
                "last_error": None,
            }
        )
    aligned_set_sink = CompositeAlignedSetSink(aligned_set_sinks)

    def handle_aligned_set(aligned_set, sync_snapshot, camera_snapshot) -> None:
        nonlocal aligned_set_count, recording_failure_reported
        if stop_requested.is_set():
            return
        aligned_set_sink.publish(
            AlignedSetEvent(
                aligned_set=aligned_set,
                sync_snapshot=sync_snapshot,
                camera_snapshot=camera_snapshot,
            )
        )
        if recording_publish_sink is not None:
            status = recording_publish_sink.last_status
            if recording_publish_sink.last_submit_accepted is False and not recording_failure_reported:
                if status.last_error is not None:
                    print(f"Recording degraded: {status.last_error}", flush=True)
                recording_failure_reported = True
        aligned_set_count += 1
        if args.stop_after_aligned_sets is not None and aligned_set_count >= args.stop_after_aligned_sets:
            request_shutdown(
                f"reached target aligned set count: {aligned_set_count}",
                mark_error=False,
            )

    runner = SynchronizedStreamRunner(
        config,
        on_aligned_set=handle_aligned_set,
        on_error=request_shutdown,
    )
    capture_thread = threading.Thread(
        target=lambda: asyncio.run(runner.run_until_stopped(stop_requested)),
        name="sync-stream-capture",
        daemon=True,
    )
    capture_thread.start()

    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def _handle_sigterm(_signum, _frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _handle_sigterm)
    print(f"Serving synchronized stream on http://{config.stream.host}:{config.stream.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
        stop_requested.set()
        if zmq_publish_sink is not None:
            zmq_publish_sink.close()
        repository.stop()
        server.server_close()
        capture_thread.join(timeout=10)
        final_recording_status = close_recording_sink(recording_sink, repository)
        if final_recording_status is not None and final_recording_status.failed:
            message = final_recording_status.last_error or "recording failed"
            print(f"Recording failed before shutdown completed: {message}", flush=True)
            raise SystemExit(2)


def close_recording_sink(
    recording_sink: RecordingSink | None,
    repository,
):
    if recording_sink is None:
        return None
    recording_sink.close()
    status = recording_sink.status()
    repository.set_recording_status(status.as_dict())
    return status


def prepare_stream_runtime_config(template_path: str, generated_config_path: str, expected_cameras: int | None = None) -> str:
    payload = load_run_config_payload(template_path)
    cameras = payload.get("cameras", [])
    if not isinstance(cameras, list) or not cameras:
        raise ValueError("Template config must define at least one camera.")

    if all(isinstance(camera, dict) and camera.get("kind") == "hikrobot" for camera in cameras):
        return _prepare_hikrobot_runtime_config(payload, template_path, generated_config_path, expected_cameras)

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


def _prepare_hikrobot_runtime_config(
    template_payload: dict[str, Any],
    template_path: str,
    generated_config_path: str,
    expected_cameras: int | None,
) -> str:
    """Detect connected Hikrobot cameras and write a runtime config.

    Only Hikrobot USB3 Vision devices are enumerated. Any other camera
    types that may be connected to the host are intentionally ignored.
    """
    devices = discover_hikrobot_devices()
    if not devices:
        raise RuntimeError("No Hikrobot cameras detected.")
    if expected_cameras is not None and len(devices) != expected_cameras:
        raise RuntimeError(
            f"Expected {expected_cameras} Hikrobot cameras, but detected {len(devices)}: "
            f"{', '.join(d.serial for d in devices) or 'none'}"
        )
    print(
        f"Detected {len(devices)} Hikrobot camera(s): "
        f"{', '.join(d.serial for d in devices)}"
    )
    generated_payload = build_hikrobot_stream_config_payload(template_payload, devices)
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
    stream = {
        "host": "0.0.0.0",
        "port": 8787,
        "recent_sets": 4,
        "client_refresh_ms": 300,
        "preview_max_width": 1280,
        "preview_max_height": 720,
        "preview_jpeg_quality": 72,
    }
    if isinstance(generated_payload.get("stream"), dict):
        stream.update(generated_payload["stream"])
    generated_payload["stream"] = stream

    transport = {
        "enabled": False,
        "kind": "zmq",
        "bind_host": "0.0.0.0",
        "port": 5555,
        "topic": "",
        "jpeg_quality": 80,
        "max_queue": 1,
        "backpressure_strategy": "latest_only_drop_oldest",
    }
    if isinstance(generated_payload.get("transport"), dict):
        transport.update(generated_payload["transport"])
    generated_payload["transport"] = transport

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


def build_hikrobot_stream_config_payload(
    template_payload: dict[str, Any],
    devices: list[HikrobotDeviceInfo],
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
            "id": f"hik-{index:02d}",
            "kind": "hikrobot",
            "model": device.model.lower(),
            "serial": device.serial,
            "fps": int(first_camera.get("fps", 30)),
            "width": int(first_camera.get("width", 1440)),
            "height": int(first_camera.get("height", 1080)),
            "capture_image_data": True,
        }
        if first_camera.get("max_frames") is not None:
            generated_camera["max_frames"] = int(first_camera["max_frames"])
        generated_cameras.append(generated_camera)

    generated_payload = dict(template_payload)
    generated_payload["duration_s"] = 0.0
    generated_payload["cameras"] = generated_cameras

    stream = {
        "host": "0.0.0.0",
        "port": 8787,
        "recent_sets": 4,
        "client_refresh_ms": 300,
        "preview_max_width": 1280,
        "preview_max_height": 720,
        "preview_jpeg_quality": 72,
    }
    if isinstance(generated_payload.get("stream"), dict):
        stream.update(generated_payload["stream"])
    generated_payload["stream"] = stream

    transport = {
        "enabled": False,
        "kind": "zmq",
        "bind_host": "0.0.0.0",
        "port": 5555,
        "topic": "",
        "jpeg_quality": 80,
        "max_queue": 1,
        "backpressure_strategy": "latest_only_drop_oldest",
    }
    if isinstance(generated_payload.get("transport"), dict):
        transport.update(generated_payload["transport"])
    generated_payload["transport"] = transport

    sync = dict(generated_payload.get("sync", {}))
    sync["reference_camera_id"] = generated_cameras[0]["id"]
    generated_payload["sync"] = sync
    generated_payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    generated_payload["device_inventory"] = [
        {
            "serial": device.serial,
            "model": device.model,
            "manufacturer": device.manufacturer,
            "device_version": device.device_version,
            "user_defined_name": device.user_defined_name,
        }
        for device in devices
    ]
    return generated_payload


if __name__ == "__main__":
    main()

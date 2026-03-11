from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class RealSenseDeviceInfo:
    serial: str
    name: str
    model: str
    physical_port: str | None = None
    product_line: str | None = None
    usb_type: str | None = None
    firmware_version: str | None = None


def canonicalize_realsense_model(name: str) -> str:
    normalized = name.lower().replace("intel", "").replace("realsense", "").strip()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not normalized:
        return "realsense-unknown"
    return f"realsense-{normalized}"


def discover_realsense_devices(rs_module=None) -> list[RealSenseDeviceInfo]:
    if rs_module is None:
        try:
            import pyrealsense2 as rs_module  # type: ignore[assignment]
        except ImportError as exc:  # pragma: no cover - hardware/runtime path
            raise RuntimeError("pyrealsense2 is not installed in this environment.") from exc

    context = rs_module.context()
    devices = []
    for device in context.query_devices():
        name = _get_camera_info(device, rs_module, "name") or "Intel RealSense"
        serial = _get_camera_info(device, rs_module, "serial_number")
        if not serial:
            continue
        devices.append(
            RealSenseDeviceInfo(
                serial=serial,
                name=name,
                model=canonicalize_realsense_model(name),
                physical_port=_get_camera_info(device, rs_module, "physical_port"),
                product_line=_get_camera_info(device, rs_module, "product_line"),
                usb_type=_get_camera_info(device, rs_module, "usb_type_descriptor"),
                firmware_version=_get_camera_info(device, rs_module, "firmware_version"),
            )
        )
    devices.sort(key=lambda item: (item.physical_port or "", item.serial))
    return devices


def _get_camera_info(device, rs_module, attribute_name: str) -> str | None:
    camera_info = getattr(rs_module, "camera_info", None)
    if camera_info is None:
        return None
    attribute = getattr(camera_info, attribute_name, None)
    if attribute is None:
        return None
    try:
        return str(device.get_info(attribute))
    except Exception:  # pragma: no cover - SDK-specific exceptions vary
        return None

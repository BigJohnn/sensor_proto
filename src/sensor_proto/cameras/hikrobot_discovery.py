from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HikrobotDeviceInfo:
    index: int
    serial: str
    model: str
    manufacturer: str
    device_version: str
    user_defined_name: str


def discover_hikrobot_devices(mvs_module=None) -> list[HikrobotDeviceInfo]:
    """Enumerate all connected Hikrobot USB3 Vision devices."""
    if mvs_module is None:
        from sensor_proto.cameras.hikrobot import _load_mvs_sdk  # noqa: PLC0415
        mvs_module = _load_mvs_sdk()

    device_list = mvs_module.MV_CC_DEVICE_INFO_LIST()
    ret = mvs_module.MvCamera.MV_CC_EnumDevices(mvs_module.MV_USB_DEVICE, device_list)
    if ret != 0:
        raise RuntimeError(f"MVS EnumDevices failed: 0x{ret:08x}")

    import ctypes  # noqa: PLC0415

    def _decode(field) -> str:
        raw = bytes(field) if not isinstance(field, (bytes, bytearray)) else field
        return raw.decode("utf-8", errors="ignore").rstrip("\x00")

    devices: list[HikrobotDeviceInfo] = []
    for i in range(device_list.nDeviceNum):
        dev = ctypes.cast(
            device_list.pDeviceInfo[i],
            ctypes.POINTER(mvs_module.MV_CC_DEVICE_INFO),
        ).contents
        u = dev.SpecialInfo.stUsb3VInfo
        devices.append(
            HikrobotDeviceInfo(
                index=i,
                serial=_decode(u.chSerialNumber),
                model=_decode(u.chModelName),
                manufacturer=_decode(u.chVendorName),
                device_version=_decode(u.chDeviceVersion),
                user_defined_name=_decode(u.chUserDefinedName),
            )
        )
    return devices

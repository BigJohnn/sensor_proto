from __future__ import annotations

import asyncio
import ctypes
import sys
import time
from ctypes import POINTER, cast
from collections.abc import AsyncIterator

from sensor_proto.cameras.base import CameraAdapter
from sensor_proto.models import Frame

# MVS SDK installation path on Linux
_MVS_PYTHON_PATH = "/opt/MVS/Samples/64/Python"
# BGR8 packed pixel format (Hikvision GenICam extension: 0x02180015)
_PIXEL_FORMAT_BGR8 = 0x02180015


def _load_mvs_sdk():
    """Import Hikrobot MVS SDK Python bindings from installed SDK or PYTHONPATH."""
    try:
        import MvCameraControl_class as mvs  # noqa: PLC0415
        return mvs
    except ImportError:
        pass
    if _MVS_PYTHON_PATH not in sys.path:
        sys.path.insert(0, _MVS_PYTHON_PATH)
    try:
        from MvImport import MvCameraControl_class as mvs  # noqa: PLC0415
        return mvs
    except ImportError:
        pass
    try:
        import MvCameraControl_class as mvs  # noqa: PLC0415
        return mvs
    except ImportError as exc:
        raise RuntimeError(
            "Hikrobot MVS SDK not found. "
            "Download the Linux SDK from the Hikrobot website and run the installer. "
            f"Expected Python bindings at: {_MVS_PYTHON_PATH}/MvImport/"
        ) from exc


class HikrobotCameraAdapter(CameraAdapter):
    _frame_timeout_ms = 5000
    _frame_retry_backoff_s = 0.1
    _restart_retry_backoff_s = 0.5
    _restart_after_failures = 3

    def __init__(self, config, mvs_module=None) -> None:
        super().__init__(config)
        if mvs_module is None:
            mvs_module = _load_mvs_sdk()
        self._mvs = mvs_module
        self._cam = self._mvs.MvCamera()
        self._started = False

    # ------------------------------------------------------------------
    # Device lifecycle
    # ------------------------------------------------------------------

    def _enumerate_devices(self):
        device_list = self._mvs.MV_CC_DEVICE_INFO_LIST()
        ret = self._mvs.MvCamera.MV_CC_EnumDevices(self._mvs.MV_USB_DEVICE, device_list)
        if ret != 0:
            raise RuntimeError(f"MVS EnumDevices failed: 0x{ret:08x}")
        if device_list.nDeviceNum == 0:
            raise RuntimeError("No Hikrobot USB3 Vision devices found.")
        return device_list

    def _find_device_index(self, device_list) -> int:
        if not self.config.serial:
            return 0
        for i in range(device_list.nDeviceNum):
            usb_info = device_list.pDeviceInfo[i].SpecialInfo.stUsb3VInfo
            serial = bytes(usb_info.chSerialNumber).decode("utf-8", errors="ignore").rstrip("\x00")
            if serial == self.config.serial:
                return i
        raise RuntimeError(
            f"Hikrobot device with serial {self.config.serial!r} not found. "
            f"Found {device_list.nDeviceNum} device(s)."
        )

    def _open(self) -> None:
        device_list = self._enumerate_devices()
        idx = self._find_device_index(device_list)
        dev_info = cast(device_list.pDeviceInfo[idx], POINTER(self._mvs.MV_CC_DEVICE_INFO)).contents
        ret = self._cam.MV_CC_CreateHandle(dev_info)
        if ret != 0:
            raise RuntimeError(f"MVS CreateHandle failed: 0x{ret:08x}")
        ret = self._cam.MV_CC_OpenDevice(self._mvs.MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise RuntimeError(f"MVS OpenDevice failed: 0x{ret:08x}")
        # Configure pixel format and frame rate
        self._cam.MV_CC_SetEnumValue("PixelFormat", _PIXEL_FORMAT_BGR8)
        self._cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
        self._cam.MV_CC_SetFloatValue("AcquisitionFrameRate", float(self.config.fps))

    def _start_grabbing(self) -> None:
        ret = self._cam.MV_CC_StartGrabbing()
        if ret != 0:
            raise RuntimeError(f"MVS StartGrabbing failed: 0x{ret:08x}")
        self._started = True

    def _stop_grabbing(self) -> None:
        if not self._started:
            return
        try:
            self._cam.MV_CC_StopGrabbing()
        except Exception:
            pass
        self._started = False

    def _close_device(self) -> None:
        try:
            self._cam.MV_CC_CloseDevice()
        except Exception:
            pass
        try:
            self._cam.MV_CC_DestroyHandle()
        except Exception:
            pass

    def _restart(self) -> None:
        self._stop_grabbing()
        self._close_device()
        self._cam = self._mvs.MvCamera()
        self._open()
        self._start_grabbing()

    # ------------------------------------------------------------------
    # Frame retrieval
    # ------------------------------------------------------------------

    def _next_frame(self) -> dict[str, object]:
        stOutFrame = self._mvs.MV_FRAME_OUT()
        ret = self._cam.MV_CC_GetImageBuffer(stOutFrame, self._frame_timeout_ms)
        if ret != 0:
            raise RuntimeError(f"MVS GetImageBuffer failed: 0x{ret:08x}")
        try:
            fi = stOutFrame.stFrameInfo
            payload_size = int(fi.nFrameLen)
            device_ts_ns = (int(fi.nDevTimeStampHigh) << 32) | int(fi.nDevTimeStampLow)
            device_timestamp_ms = device_ts_ns / 1_000_000.0
            frame_counter = int(fi.nFrameNum)
            image_data: bytes | None = None
            if self.config.capture_image_data and payload_size > 0 and stOutFrame.pBufAddr:
                pdata = ctypes.cast(
                    stOutFrame.pBufAddr,
                    ctypes.POINTER(ctypes.c_ubyte * payload_size),
                )
                image_data = bytes(pdata.contents)
        finally:
            self._cam.MV_CC_FreeImageBuffer(stOutFrame)
        return {
            "payload_size": payload_size,
            "device_timestamp_ms": device_timestamp_ms,
            "frame_counter": frame_counter,
            "image_data": image_data,
        }

    def _is_recoverable_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        # MV_E_TIMEOUT = 0x80000006
        return "timeout" in msg or "0x80000006" in msg or "getimage" in msg

    async def _next_frame_with_recovery(
        self, consecutive_failures: int
    ) -> tuple[dict[str, object] | None, int]:
        try:
            frame_data = await asyncio.to_thread(self._next_frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._is_recoverable_error(exc):
                raise
            consecutive_failures += 1
            if consecutive_failures >= self._restart_after_failures:
                print(
                    f"{self.config.id}: frame retrieval stalled after "
                    f"{consecutive_failures} recoverable errors; restarting device.",
                    flush=True,
                )
                try:
                    await asyncio.to_thread(self._restart)
                except Exception as restart_exc:
                    print(f"{self.config.id}: device restart failed: {restart_exc}", flush=True)
                    await asyncio.sleep(self._restart_retry_backoff_s)
                    return None, consecutive_failures
                await asyncio.sleep(self._restart_retry_backoff_s)
                return None, 0
            await asyncio.sleep(self._frame_retry_backoff_s)
            return None, consecutive_failures
        return frame_data, 0

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------

    async def frames(self) -> AsyncIterator[Frame]:
        await asyncio.to_thread(self._open)
        await asyncio.to_thread(self._start_grabbing)
        sequence = 0
        consecutive_failures = 0
        try:
            while True:
                frame_data, consecutive_failures = await self._next_frame_with_recovery(
                    consecutive_failures
                )
                if frame_data is None:
                    continue
                host_received_at = time.monotonic()
                yield Frame(
                    camera_id=self.config.id,
                    camera_kind=self.config.kind,
                    sequence=sequence,
                    created_at=host_received_at,
                    payload_size=frame_data["payload_size"],
                    host_received_at=host_received_at,
                    device_timestamp_ms=frame_data["device_timestamp_ms"],
                    timestamp_domain="hikrobot-device-clock",
                    frame_counter=frame_data["frame_counter"],
                    sensor_serial=self.config.serial,
                    width=self.config.width,
                    height=self.config.height,
                    pixel_format="bgr8" if self.config.capture_image_data else None,
                    image_data=frame_data["image_data"],
                )
                sequence += 1
        finally:
            await self.close()

    async def close(self) -> None:
        await asyncio.to_thread(self._stop_grabbing)
        await asyncio.to_thread(self._close_device)

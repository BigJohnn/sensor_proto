"""Dual Hikrobot MV-CS016-10UC preview: grab both cameras concurrently, display side-by-side."""
from __future__ import annotations

import os
import sys
import threading
import time
from ctypes import POINTER, cast
from typing import Optional

import cv2
import numpy as np

# MVS SDK
sys.path.insert(0, "/opt/MVS/Samples/64/Python/MvImport")
os.environ.setdefault("MVCAM_COMMON_RUNENV", "/opt/MVS/lib")

from MvCameraControl_class import (  # noqa: E402
    MV_ACCESS_Exclusive,
    MV_CC_DEVICE_INFO,
    MV_CC_DEVICE_INFO_LIST,
    MV_FRAME_OUT,
    MV_USB_DEVICE,
    MVCC_ENUMVALUE,
    MVCC_FLOATVALUE,
    MVCC_INTVALUE,
    MvCamera,
)

# ── Config ────────────────────────────────────────────────────────────────────
SERIALS = ["DA5404769", "DA5404760"]   # order → left, right
FPS = 10
DISPLAY_W = 960   # 960×720 per panel → 720p (4:3 from 1440×1080)
WINDOW = "Dual Cam Preview  |  Q:quit  A/Z:exp  G/B:gain  W:AWB-once  T:AWB-cont  R/F/C:WB-R/G/B+"
PIXEL_FORMAT_BGR8 = 0x02180015

# Default camera settings applied at startup (all auto)
EXPOSURE_AUTO = 2   # 2=Continuous
GAIN_AUTO = 2
WB_AUTO = 2


def _decode(arr) -> str:
    return bytes(arr).decode("utf-8", errors="ignore").rstrip("\x00")


# ── Camera worker ─────────────────────────────────────────────────────────────
class CamWorker:
    def __init__(self, label: str, dev_info: MV_CC_DEVICE_INFO) -> None:
        self.label = label
        self._dev_info = dev_info
        self._cam = MvCamera()
        self._lock = threading.Lock()
        self._latest: Optional[np.ndarray] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.fps_actual = 0.0

    def start(self) -> None:
        ret = self._cam.MV_CC_CreateHandle(self._dev_info)
        if ret != 0:
            raise RuntimeError(f"[{self.label}] CreateHandle failed: 0x{ret:08x}")
        ret = self._cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise RuntimeError(f"[{self.label}] OpenDevice failed: 0x{ret:08x}")
        self._cam.MV_CC_SetEnumValue("PixelFormat", PIXEL_FORMAT_BGR8)
        self._cam.MV_CC_SetEnumValue("ExposureAuto", EXPOSURE_AUTO)
        self._cam.MV_CC_SetEnumValue("GainAuto", GAIN_AUTO)
        self._cam.MV_CC_SetEnumValue("BalanceWhiteAuto", WB_AUTO)
        self._cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
        self._cam.MV_CC_SetFloatValue("AcquisitionFrameRate", float(FPS))
        ret = self._cam.MV_CC_StartGrabbing()
        if ret != 0:
            raise RuntimeError(f"[{self.label}] StartGrabbing failed: 0x{ret:08x}")
        self._running = True
        self._thread = threading.Thread(target=self._grab_loop, daemon=True, name=f"cam-{self.label}")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        try:
            self._cam.MV_CC_StopGrabbing()
            self._cam.MV_CC_CloseDevice()
            self._cam.MV_CC_DestroyHandle()
        except Exception:
            pass

    def latest_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._latest.copy() if self._latest is not None else None

    def get_exposure(self) -> float:
        from MvCameraControl_class import MVCC_FLOATVALUE  # noqa: PLC0415
        v = MVCC_FLOATVALUE()
        return v.fCurValue if self._cam.MV_CC_GetFloatValue("ExposureTime", v) == 0 else 0.0

    def set_exposure_manual(self, us: float) -> None:
        self._cam.MV_CC_SetEnumValue("ExposureAuto", 0)  # Off
        v = MVCC_FLOATVALUE()
        if self._cam.MV_CC_GetFloatValue("ExposureTime", v) == 0:
            us = max(v.fMin, min(v.fMax, us))
        self._cam.MV_CC_SetFloatValue("ExposureTime", us)

    def set_gain_manual(self, db: float) -> None:
        self._cam.MV_CC_SetEnumValue("GainAuto", 0)  # Off
        v = MVCC_FLOATVALUE()
        if self._cam.MV_CC_GetFloatValue("Gain", v) == 0:
            db = max(v.fMin, min(v.fMax, db))
        self._cam.MV_CC_SetFloatValue("Gain", db)

    def adjust_exposure(self, factor: float) -> float:
        """Multiply current exposure by factor. Returns new value."""
        self._cam.MV_CC_SetEnumValue("ExposureAuto", 0)
        v = MVCC_FLOATVALUE()
        if self._cam.MV_CC_GetFloatValue("ExposureTime", v) != 0:
            return 0.0
        new_val = max(v.fMin, min(v.fMax, v.fCurValue * factor))
        self._cam.MV_CC_SetFloatValue("ExposureTime", new_val)
        return new_val

    def adjust_gain(self, delta_db: float) -> float:
        """Add delta_db to current gain. Returns new value."""
        self._cam.MV_CC_SetEnumValue("GainAuto", 0)
        v = MVCC_FLOATVALUE()
        if self._cam.MV_CC_GetFloatValue("Gain", v) != 0:
            return 0.0
        new_val = max(v.fMin, min(v.fMax, v.fCurValue + delta_db))
        self._cam.MV_CC_SetFloatValue("Gain", new_val)
        return new_val

    # ── White balance ──────────────────────────────────────────────────────
    # BalanceWhiteAuto: 0=Off, 1=Once, 2=Continuous
    # BalanceRatioSelector: 0=Red, 1=Green, 2=Blue
    # BalanceRatio: float (typical range 1–4095)

    def get_wb_auto(self) -> int:
        """Return current BalanceWhiteAuto value (0/1/2)."""
        v = MVCC_ENUMVALUE()
        if self._cam.MV_CC_GetEnumValue("BalanceWhiteAuto", v) == 0:
            return int(v.nCurValue)
        return -1

    def awb_once(self) -> None:
        """Trigger a single auto white balance pass."""
        self._cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 1)

    def set_awb_continuous(self, enable: bool) -> None:
        self._cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 2 if enable else 0)

    def adjust_wb_ratio(self, channel: int, delta: int) -> int:
        """Manually adjust white balance ratio for one channel.
        channel: 0=Red, 1=Green, 2=Blue. delta: additive integer step.
        BalanceRatio is an integer node (Red≈1458, Green≈1024, Blue≈1957).
        Returns new ratio value."""
        self._cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 0)
        self._cam.MV_CC_SetEnumValue("BalanceRatioSelector", channel)
        v = MVCC_INTVALUE()
        if self._cam.MV_CC_GetIntValue("BalanceRatio", v) != 0:
            return 0
        new_val = int(max(v.nMin, min(v.nMax, v.nCurValue + delta)))
        self._cam.MV_CC_SetIntValue("BalanceRatio", new_val)
        return new_val

    def get_wb_ratios(self) -> tuple[int, int, int]:
        """Read current R/G/B balance ratios (integer node)."""
        ratios = []
        for ch in range(3):
            self._cam.MV_CC_SetEnumValue("BalanceRatioSelector", ch)
            v = MVCC_INTVALUE()
            ratios.append(int(v.nCurValue) if self._cam.MV_CC_GetIntValue("BalanceRatio", v) == 0 else 0)
        return tuple(ratios)  # (R, G, B)

    def _grab_loop(self) -> None:
        import ctypes

        frame_count = 0
        t0 = time.monotonic()

        while self._running:
            stOutFrame = MV_FRAME_OUT()
            ret = self._cam.MV_CC_GetImageBuffer(stOutFrame, 2000)
            if ret != 0:
                continue  # timeout or error — keep trying

            fi = stOutFrame.stFrameInfo
            w, h, size = int(fi.nWidth), int(fi.nHeight), int(fi.nFrameLen)

            try:
                pdata = ctypes.cast(stOutFrame.pBufAddr, ctypes.POINTER(ctypes.c_ubyte * size))
                img = np.frombuffer(pdata.contents, dtype=np.uint8).reshape(h, w, 3).copy()
            finally:
                self._cam.MV_CC_FreeImageBuffer(stOutFrame)

            with self._lock:
                self._latest = img

            frame_count += 1
            elapsed = time.monotonic() - t0
            if elapsed >= 1.0:
                self.fps_actual = frame_count / elapsed
                frame_count = 0
                t0 = time.monotonic()


# ── Device enumeration ────────────────────────────────────────────────────────
def find_devices() -> dict[str, MV_CC_DEVICE_INFO]:
    dl = MV_CC_DEVICE_INFO_LIST()
    ret = MvCamera.MV_CC_EnumDevices(MV_USB_DEVICE, dl)
    if ret != 0:
        raise RuntimeError(f"EnumDevices failed: 0x{ret:08x}")
    found: dict[str, MV_CC_DEVICE_INFO] = {}
    for i in range(dl.nDeviceNum):
        dev = cast(dl.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
        serial = _decode(dev.SpecialInfo.stUsb3VInfo.chSerialNumber)
        found[serial] = dev
    return found


# ── Display helpers ───────────────────────────────────────────────────────────
_WB_AUTO_LABELS = {0: "WB:off", 1: "WB:once", 2: "WB:auto", -1: "WB:?"}


def make_panel(
    img: Optional[np.ndarray],
    label: str,
    fps: float,
    exposure_us: float,
    wb_auto: int,
    wb_ratios: tuple,
    target_w: int,
) -> np.ndarray:
    target_h = target_w * 3 // 4  # 4:3 aspect
    if img is None:
        panel = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        cv2.putText(panel, f"{label}: waiting...", (20, target_h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 100), 2)
        return panel

    panel = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

    # Row 1: label / fps / exposure
    cv2.rectangle(panel, (0, 0), (target_w, 52), (0, 0, 0), -1)
    exp_str = f"{exposure_us/1000:.1f}ms" if exposure_us else "auto"
    cv2.putText(panel, f"{label}  {fps:.1f}fps  exp={exp_str}",
                (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 120), 1, cv2.LINE_AA)
    # Row 2: white balance
    r, g, b = wb_ratios
    wb_str = f"{_WB_AUTO_LABELS.get(wb_auto, '?')}  R={r} G={g} B={b}"
    cv2.putText(panel, wb_str,
                (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 200, 255), 1, cv2.LINE_AA)
    return panel


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    print("Enumerating cameras...")
    devices = find_devices()
    print(f"Found: {list(devices.keys())}")

    workers: list[CamWorker] = []
    labels: list[str] = []

    for serial in SERIALS:
        if serial not in devices:
            print(f"WARNING: serial {serial} not found — skipping")
            continue
        label = f"hik-{len(workers):02d} [{serial[-4:]}]"
        w = CamWorker(label, devices[serial])
        w.start()
        workers.append(w)
        labels.append(label)
        print(f"  Started {label}")

    if not workers:
        print("No cameras started. Exiting.")
        return

    print(f"\n{WINDOW}")
    print("  A / Z     : exposure  ×1.5 / ×0.67")
    print("  G / B     : gain  +1 dB / -1 dB")
    print("  W         : AWB Once (single-shot white balance)")
    print("  T         : toggle AWB Continuous on/off")
    print("  R / E     : WB Red ratio  +50 / -50")
    print("  F / D     : WB Green ratio  +50 / -50")
    print("  C / X     : WB Blue ratio  +50 / -50")
    print("  0         : reset all auto (AE + AG + AWB continuous)")
    print("  Q / ESC   : quit\n")

    win_w = DISPLAY_W * len(workers)
    win_h = DISPLAY_W * 3 // 4
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, win_w, win_h)

    try:
        while True:
            panels = [
                make_panel(
                    w.latest_frame(), w.label, w.fps_actual,
                    w.get_exposure(), w.get_wb_auto(), w.get_wb_ratios(),
                    DISPLAY_W,
                )
                for w in workers
            ]
            mosaic = np.hstack(panels)
            cv2.imshow(WINDOW, mosaic)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            elif key == ord("a"):
                vals = [w.adjust_exposure(1.5) for w in workers]
                print(f"Exposure → {vals[0]:.0f} µs")
            elif key == ord("z"):
                vals = [w.adjust_exposure(1 / 1.5) for w in workers]
                print(f"Exposure → {vals[0]:.0f} µs")
            elif key == ord("g"):
                vals = [w.adjust_gain(1.0) for w in workers]
                print(f"Gain → {vals[0]:.2f} dB")
            elif key == ord("b"):
                vals = [w.adjust_gain(-1.0) for w in workers]
                print(f"Gain → {vals[0]:.2f} dB")
            elif key == ord("w"):
                for w in workers:
                    w.awb_once()
                print("AWB Once triggered")
            elif key == ord("t"):
                cur = workers[0].get_wb_auto() if workers else 0
                enable = cur != 2
                for w in workers:
                    w.set_awb_continuous(enable)
                print(f"AWB Continuous {'ON' if enable else 'OFF'}")
            elif key == ord("r"):
                vals = [w.adjust_wb_ratio(0, 50) for w in workers]
                print(f"WB Red → {vals[0]:.0f}")
            elif key == ord("e"):
                vals = [w.adjust_wb_ratio(0, -50) for w in workers]
                print(f"WB Red → {vals[0]:.0f}")
            elif key == ord("f"):
                vals = [w.adjust_wb_ratio(1, 50) for w in workers]
                print(f"WB Green → {vals[0]:.0f}")
            elif key == ord("d"):
                vals = [w.adjust_wb_ratio(1, -50) for w in workers]
                print(f"WB Green → {vals[0]:.0f}")
            elif key == ord("c"):
                vals = [w.adjust_wb_ratio(2, 50) for w in workers]
                print(f"WB Blue → {vals[0]:.0f}")
            elif key == ord("x"):
                vals = [w.adjust_wb_ratio(2, -50) for w in workers]
                print(f"WB Blue → {vals[0]:.0f}")
            elif key == ord("0"):
                for w in workers:
                    w._cam.MV_CC_SetEnumValue("ExposureAuto", 2)
                    w._cam.MV_CC_SetEnumValue("GainAuto", 2)
                    w._cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 2)
                print("AE + AG + AWB all set to Continuous")

    finally:
        print("Stopping cameras...")
        for w in workers:
            w.stop()
        cv2.destroyAllWindows()
        print("Done.")


if __name__ == "__main__":
    main()

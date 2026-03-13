from __future__ import annotations

from sensor_proto.cameras.base import CameraAdapter
from sensor_proto.cameras.hikrobot import HikrobotCameraAdapter
from sensor_proto.cameras.mock import MockCameraAdapter
from sensor_proto.cameras.orbbec import OrbbecCameraAdapter
from sensor_proto.cameras.realsense import RealSenseCameraAdapter
from sensor_proto.config import CameraConfig


def create_camera_adapter(config: CameraConfig) -> CameraAdapter:
    if config.kind == "mock":
        return MockCameraAdapter(config)
    if config.kind == "realsense":
        return RealSenseCameraAdapter(config)
    if config.kind == "orbbec":
        return OrbbecCameraAdapter(config)
    if config.kind == "hikrobot":
        return HikrobotCameraAdapter(config)
    raise ValueError(f"Unsupported camera kind: {config.kind}")


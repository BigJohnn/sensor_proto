from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from sensor_proto.config import CameraConfig
from sensor_proto.models import Frame


class CameraAdapter(ABC):
    def __init__(self, config: CameraConfig) -> None:
        self.config = config

    @abstractmethod
    async def frames(self) -> AsyncIterator[Frame]:
        raise NotImplementedError

    async def close(self) -> None:
        return None


from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ZmqTransportConfig:
    bind_host: str = "0.0.0.0"
    port: int = 5555
    topic: str = ""
    jpeg_quality: int = 80
    max_queue: int = 1
    backpressure_strategy: str = "latest_only_drop_oldest"

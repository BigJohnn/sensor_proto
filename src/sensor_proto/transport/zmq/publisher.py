from __future__ import annotations

from collections.abc import Callable

from sensor_proto.models import AlignedFrameSet
from sensor_proto.transport.zmq.config import ZmqTransportConfig
from sensor_proto.transport.zmq.encoding import encode_aligned_set_multipart


class ZmqAlignedSetPublisher:
    def __init__(
        self,
        config: ZmqTransportConfig,
        *,
        zmq_module=None,
        multipart_encoder: Callable[[AlignedFrameSet, list[str]], list[bytes]] | None = None,
    ) -> None:
        self._config = config
        self._zmq_module = zmq_module
        self._multipart_encoder = multipart_encoder or (
            lambda aligned_set, camera_order: encode_aligned_set_multipart(
                aligned_set,
                camera_order,
                jpeg_quality=self._config.jpeg_quality,
            )
        )
        self._context = None
        self._socket = None

    @property
    def bind_endpoint(self) -> str:
        return f"tcp://{self._config.bind_host}:{self._config.port}"

    def open(self) -> None:
        if self._socket is not None:
            return
        zmq = self._zmq_module or _load_zmq_module()
        self._context = zmq.Context.instance()
        self._socket = self._context.socket(zmq.PUB)
        self._configure_socket(zmq, self._socket)
        self._socket.bind(self.bind_endpoint)

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None
        self._context = None

    def publish(self, aligned_set: AlignedFrameSet, camera_order: list[str]) -> None:
        if self._socket is None:
            raise RuntimeError("ZMQ publisher is not open.")
        zmq = self._zmq_module or _load_zmq_module()
        parts = self._multipart_encoder(
            aligned_set,
            camera_order,
        )
        try:
            self._socket.send_multipart(parts, flags=getattr(zmq, "DONTWAIT", 0))
        except Exception as exc:
            if _is_would_block(exc, zmq):
                raise ZmqPublishWouldBlock("ZMQ publisher send would block under current backpressure.") from exc
            raise

    def _configure_socket(self, zmq, socket) -> None:
        hwm = max(int(self._config.max_queue), 1)
        if hasattr(socket, "set_hwm"):
            socket.set_hwm(hwm)
            return
        if hasattr(socket, "setsockopt") and hasattr(zmq, "SNDHWM"):
            socket.setsockopt(zmq.SNDHWM, hwm)


class ZmqPublishWouldBlock(RuntimeError):
    pass


def _load_zmq_module():
    try:
        import zmq
    except ImportError as exc:  # pragma: no cover - depends on runtime environment
        raise RuntimeError("ZMQ transport requires the `pyzmq` package in the runtime environment.") from exc
    return zmq


def _is_would_block(exc: Exception, zmq) -> bool:
    again_type = getattr(zmq, "Again", None)
    if again_type is not None and isinstance(exc, again_type):
        return True
    errno_value = getattr(exc, "errno", None)
    eagain = getattr(zmq, "EAGAIN", None)
    return eagain is not None and errno_value == eagain

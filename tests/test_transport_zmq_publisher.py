from __future__ import annotations

import unittest

from sensor_proto.models import AlignedFrameSet
from sensor_proto.transport.zmq import ZmqAlignedSetPublisher, ZmqTransportConfig


class _FakeSocket:
    def __init__(self) -> None:
        self.bound: list[str] = []
        self.sent: list[tuple[list[bytes], int]] = []
        self.closed_with: list[int] = []
        self.hwm: list[int] = []

    def bind(self, endpoint: str) -> None:
        self.bound.append(endpoint)

    def send_multipart(self, parts: list[bytes], flags: int = 0) -> None:
        self.sent.append((parts, flags))

    def close(self, linger: int = 0) -> None:
        self.closed_with.append(linger)

    def set_hwm(self, value: int) -> None:
        self.hwm.append(value)


class _FakeContext:
    def __init__(self, socket: _FakeSocket) -> None:
        self._socket = socket
        self.requested_socket_types: list[int] = []

    def socket(self, socket_type: int) -> _FakeSocket:
        self.requested_socket_types.append(socket_type)
        return self._socket


class _FakeContextFactory:
    def __init__(self, context: _FakeContext) -> None:
        self._context = context

    def instance(self) -> _FakeContext:
        return self._context


class _FakeZmqModule:
    PUB = 1
    DONTWAIT = 2

    def __init__(self, context: _FakeContext) -> None:
        self.Context = _FakeContextFactory(context)


class ZmqPublisherTests(unittest.TestCase):
    def test_publish_requires_open(self) -> None:
        publisher = ZmqAlignedSetPublisher(ZmqTransportConfig())

        with self.assertRaisesRegex(RuntimeError, "not open"):
            publisher.publish(
                AlignedFrameSet(
                    set_id=1,
                    reference_camera_id="cam-a",
                    reference_timestamp_s=1.0,
                    skew_ms=0.0,
                ),
                ["cam-a"],
            )

    def test_open_binds_endpoint_and_publish_sends_encoded_parts(self) -> None:
        fake_socket = _FakeSocket()
        fake_context = _FakeContext(fake_socket)
        fake_zmq = _FakeZmqModule(fake_context)
        encoded_parts = [b"envelope", b"meta", b"payload"]

        publisher = ZmqAlignedSetPublisher(
            ZmqTransportConfig(bind_host="127.0.0.1", port=5560),
            zmq_module=fake_zmq,
            multipart_encoder=lambda aligned_set, camera_order: encoded_parts,
        )

        publisher.open()
        publisher.publish(
            AlignedFrameSet(
                set_id=2,
                reference_camera_id="cam-a",
                reference_timestamp_s=2.0,
                skew_ms=1.0,
            ),
            ["cam-a"],
        )
        publisher.close()

        self.assertEqual(fake_socket.bound, ["tcp://127.0.0.1:5560"])
        self.assertEqual(fake_socket.hwm, [1])
        self.assertEqual(fake_context.requested_socket_types, [fake_zmq.PUB])
        self.assertEqual(fake_socket.sent, [(encoded_parts, fake_zmq.DONTWAIT)])
        self.assertEqual(fake_socket.closed_with, [0])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import socket
import time
import unittest

import zmq

from sensor_proto.models import AlignedFrameSet, Frame
from sensor_proto.transport.zmq import ZmqAlignedSetPublisher, ZmqTransportConfig, decode_aligned_set_multipart


def _find_free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ZmqIntegrationTests(unittest.TestCase):
    def test_localhost_pub_sub_round_trip_decodes_one_aligned_set(self) -> None:
        port = _find_free_tcp_port()
        aligned_set = AlignedFrameSet(
            set_id=41,
            reference_camera_id="cam-a",
            reference_timestamp_s=123.456,
            skew_ms=1.25,
            frames={
                "cam-a": Frame(
                    camera_id="cam-a",
                    camera_kind="mock",
                    sequence=1,
                    created_at=1.0,
                    payload_size=3,
                    device_timestamp_ms=1000.0,
                    width=1,
                    height=1,
                    pixel_format="bgr8",
                    image_data=b"\x00\x00\x00",
                ),
                "cam-b": Frame(
                    camera_id="cam-b",
                    camera_kind="mock",
                    sequence=2,
                    created_at=1.0,
                    payload_size=3,
                    device_timestamp_ms=1008.0,
                    width=1,
                    height=1,
                    pixel_format="bgr8",
                    image_data=b"\x01\x02\x03",
                ),
            },
            offsets_ms={"cam-a": 0.0, "cam-b": 8.0},
        )
        publisher = ZmqAlignedSetPublisher(
            ZmqTransportConfig(
                bind_host="127.0.0.1",
                port=port,
                max_queue=1,
            )
        )
        context = zmq.Context.instance()
        subscriber = context.socket(zmq.SUB)
        subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
        subscriber.setsockopt(zmq.RCVTIMEO, 250)
        subscriber.connect(f"tcp://127.0.0.1:{port}")
        try:
            publisher.open()
            time.sleep(0.2)
            multipart = None
            for _ in range(6):
                publisher.publish(aligned_set, ["cam-a", "cam-b"])
                try:
                    multipart = subscriber.recv_multipart()
                    break
                except zmq.error.Again:
                    time.sleep(0.05)
            self.assertIsNotNone(multipart)
            assert multipart is not None
            decoded = decode_aligned_set_multipart(multipart)
        finally:
            subscriber.close(linger=0)
            publisher.close()

        self.assertEqual(decoded.envelope["set_id"], 41)
        self.assertEqual(decoded.envelope["camera_order"], ["cam-a", "cam-b"])
        self.assertEqual([camera.metadata["camera_id"] for camera in decoded.cameras], ["cam-a", "cam-b"])
        self.assertEqual(len(decoded.cameras), 2)


if __name__ == "__main__":
    unittest.main()

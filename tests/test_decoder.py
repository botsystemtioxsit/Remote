import fractions
import socket
import struct
import threading
import time
import unittest

import av
import numpy as np

from phonecast.media import VideoDecoder


def encode(n, gop):
    codec = av.CodecContext.create("libx264", "w")
    codec.width, codec.height = 320, 240
    codec.pix_fmt = "yuv420p"
    codec.time_base = fractions.Fraction(1, 60)
    codec.options = {"tune": "zerolatency", "preset": "ultrafast", "g": str(gop)}
    out = []
    for i in range(n):
        img = np.full((240, 320, 3), i * 4 % 256, dtype=np.uint8)
        f = av.VideoFrame.from_ndarray(img, format="rgb24")
        f.pts = i
        out += [(bytes(p), p.is_keyframe) for p in codec.encode(f)]
    return out


def packet(data, key, pts):
    return struct.pack(">QI", ((1 << 62) if key else 0) | pts, len(data)) + data


class LagGuardTest(unittest.TestCase):
    def test_drops_backlog_and_resyncs_on_keyframe(self):
        pkts = encode(60, gop=20)  # keyframes at 0, 20, 40
        self.assertTrue(pkts[0][1] and pkts[20][1] and pkts[40][1])
        a, b = socket.socketpair()
        requests = []
        dec = VideoDecoder(b, request_keyframe=lambda: requests.append(1))
        dec.start()
        now_us = lambda: int(time.monotonic() * 1e6)  # noqa: E731

        # 0..9 on time
        for data, key in pkts[:10]:
            a.sendall(packet(data, key, now_us()))
        time.sleep(0.3)
        self.assertEqual(dec.frame_count, 10)
        # 10..19 arrive 1 s late (a backlog): must be skipped, keyframe requested
        for data, key in pkts[10:20]:
            a.sendall(packet(data, key, now_us() - 1_000_000))
        time.sleep(0.3)
        self.assertEqual(dec.frame_count, 10)
        self.assertEqual(dec.drop_count, 1)
        self.assertEqual(len(requests), 1)
        # the next keyframe (20) resumes decoding with a clean picture
        for data, key in pkts[20:30]:
            a.sendall(packet(data, key, now_us()))
        time.sleep(0.3)
        self.assertEqual(dec.frame_count, 20)
        frame = dec.take_frame()
        self.assertEqual((frame.width, frame.height), (320, 240))
        a.close()
        dec.join(2)


if __name__ == "__main__":
    unittest.main()

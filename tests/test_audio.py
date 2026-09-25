import os
import socket
import struct
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_adb import opus_packets  # noqa: E402

from phonecast.media import AudioPlayer  # noqa: E402


class AudioTest(unittest.TestCase):
    def test_opus_stream_is_decoded_to_pcm(self):
        head, packets = opus_packets(1.0)
        a, b = socket.socketpair()
        out = tempfile.NamedTemporaryFile(delete=False).name
        player = AudioPlayer(b, ["sh", "-c", "cat > '%s'" % out], "opus")
        player.start()
        a.sendall(struct.pack(">QI", 1 << 63, len(head)) + head)
        for p in packets:
            a.sendall(struct.pack(">QI", 0, len(p)) + p)
        a.close()
        player.join(5)
        player._proc.wait(5)
        pcm = np.fromfile(out, dtype=np.int16).reshape(-1, 2)
        os.remove(out)
        # ~1 s of 48 kHz stereo s16, same tone on both channels, right loudness
        self.assertGreater(len(pcm), 46000)
        self.assertLess(len(pcm), 49000)
        self.assertTrue(7000 < np.abs(pcm[5000:, 0]).max() < 9000)
        self.assertTrue(np.array_equal(pcm[:, 0], pcm[:, 1]))


if __name__ == "__main__":
    unittest.main()

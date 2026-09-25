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


class AudioLagTest(unittest.TestCase):
    def test_late_audio_is_skipped_and_playback_continues(self):
        import time
        head, packets = opus_packets(1.0)          # 50 packets of 20 ms
        a, b = socket.socketpair()
        out = tempfile.NamedTemporaryFile(delete=False).name
        player = AudioPlayer(b, ["sh", "-c", "cat > '%s'" % out], "opus")
        player.start()
        now_us = lambda: int(time.monotonic() * 1e6)  # noqa: E731
        a.sendall(struct.pack(">QI", 1 << 63, len(head)) + head)
        for p in packets[:15]:                      # on time
            a.sendall(struct.pack(">QI", now_us(), len(p)) + p)
            time.sleep(0.02)
        for p in packets[15:35]:                    # a burst 0.5 s late (a backlog)
            a.sendall(struct.pack(">QI", now_us() - 500_000, len(p)) + p)
        time.sleep(0.05)
        for p in packets[35:]:                      # on time again
            a.sendall(struct.pack(">QI", now_us(), len(p)) + p)
            time.sleep(0.02)
        a.close()
        player.join(5)
        player._proc.wait(5)
        played = len(np.fromfile(out, dtype=np.int16)) // 2 / 960   # in 20 ms packets
        os.remove(out)
        self.assertGreaterEqual(player.skipped, 15)      # the late burst was dropped
        self.assertGreaterEqual(played, 25)              # the rest was played
        self.assertLessEqual(played, 36)


if __name__ == "__main__":
    unittest.main()

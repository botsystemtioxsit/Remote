"""Video decoding and audio playback threads."""

import shutil
import subprocess
import sys
import threading
import time

import av

from .session import read_packet


# If the picture lags this far behind the phone, drop what is queued and ask
# the phone for a fresh keyframe instead of letting the delay keep growing.
MAX_LAG_US = 250_000


class VideoDecoder(threading.Thread):
    """Reads H.264 packets from the socket and keeps only the newest frame.

    Every packet has to be decoded (frames depend on each other), but the
    expensive RGB conversion is left to the UI, which only converts the frame
    it actually shows. When the stream arrives faster than this machine can
    decode it, stale packets are skipped until the next keyframe, so latency
    stays bounded instead of accumulating.
    """

    def __init__(self, sock, on_eof=None, request_keyframe=None):
        super().__init__(daemon=True, name="video")
        self.sock = sock
        self.on_eof = on_eof
        self.request_keyframe = request_keyframe
        self.frame_size = (0, 0)    # native video size, used for touch coordinates
        self._lock = threading.Lock()
        self._latest = None         # newest decoded av.VideoFrame not yet shown
        self.frame_count = 0
        self.drop_count = 0         # times the decoder fell behind and resynced
        self.error = None

    def take_frame(self):
        with self._lock:
            latest, self._latest = self._latest, None
        return latest

    def run(self):
        codec = av.CodecContext.create("h264", "r")
        try:
            codec.options = {"flags": "low_delay"}
        except (AttributeError, ValueError, TypeError):
            pass
        config = b""
        base = None          # smallest (arrival time - pts) seen: "no lag" reference
        skipping = False     # waiting for a keyframe after falling behind
        try:
            while True:
                pts, is_config, key, payload = read_packet(self.sock)
                if is_config:
                    # SPS/PPS: prepend them to the next frame packet. A new
                    # config means a new encoder session: its pts restart.
                    config = payload
                    base = None
                    continue

                d = time.monotonic() * 1e6 - pts
                if base is None or d < base:
                    base = d
                if skipping:
                    if not key:
                        continue
                    skipping = False
                elif d - base > MAX_LAG_US and not key:
                    skipping = True
                    self.drop_count += 1
                    if self.request_keyframe:
                        self.request_keyframe()
                    continue

                if config:
                    payload = config + payload
                    config = b""
                packet = av.Packet(payload)
                packet.pts = pts
                try:
                    frames = codec.decode(packet)
                except av.error.FFmpegError as e:
                    print("phonecast: decode error: %s" % e, file=sys.stderr)
                    continue
                if frames:
                    frame = frames[-1]
                    with self._lock:
                        self.frame_size = (frame.width, frame.height)
                        self._latest = frame
                        self.frame_count += len(frames)
        except (EOFError, OSError) as e:
            self.error = e
        finally:
            if self.on_eof:
                self.on_eof()


def find_audio_player():
    """Command that plays raw s16le 48 kHz stereo PCM from stdin, or None."""
    if shutil.which("pacat"):  # PulseAudio / PipeWire-pulse
        return ["pacat", "--playback", "--raw", "--format=s16le", "--rate=48000",
                "--channels=2", "--latency-msec=40", "--client-name=phonecast"]
    if shutil.which("pw-cat"):
        return ["pw-cat", "--playback", "--raw", "--format=s16", "--rate=48000",
                "--channels=2", "--latency=40ms", "-"]
    if shutil.which("aplay"):
        return ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "48000", "-c", "2",
                "--buffer-time=60000"]
    return None


class AudioPlayer(threading.Thread):
    def __init__(self, sock, command):
        super().__init__(daemon=True, name="audio")
        self.sock = sock
        self.command = command
        self.muted = False
        self._proc = None

    def run(self):
        try:
            self._proc = subprocess.Popen(self.command, stdin=subprocess.PIPE,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print("phonecast: cannot start audio player: %s" % e, file=sys.stderr)
            self._drain()
            return
        silence = b""
        try:
            while True:
                _pts, is_config, _key, payload = read_packet(self.sock)
                if is_config:
                    continue
                if self.muted:
                    if len(silence) != len(payload):
                        silence = bytes(len(payload))
                    payload = silence
                self._proc.stdin.write(payload)
                self._proc.stdin.flush()
        except (EOFError, OSError, ValueError):
            pass
        finally:
            self.stop()

    def _drain(self):
        # Keep reading so the phone never blocks on a full socket.
        try:
            while True:
                read_packet(self.sock)
        except (EOFError, OSError):
            pass

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
            self._proc.terminate()

"""Video decoding and audio playback threads."""

import shutil
import subprocess
import sys
import threading

import av

from .session import read_packet


class VideoDecoder(threading.Thread):
    """Reads H.264 packets from the socket and keeps only the newest frame.

    Frames are converted to RGB and scaled to `target_size` here, in the
    decoder thread, so the UI thread only has to blit them.
    """

    def __init__(self, sock, on_eof=None):
        super().__init__(daemon=True, name="video")
        self.sock = sock
        self.on_eof = on_eof
        self.target_size = None     # (w, h) set by the UI; None = native size
        self.frame_size = (0, 0)    # native video size, used for touch coordinates
        self._lock = threading.Lock()
        self._latest = None         # (native_size, (w, h), rgb bytes)
        self.frame_count = 0
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
        try:
            while True:
                pts, is_config, _key, payload = read_packet(self.sock)
                if is_config:
                    # SPS/PPS: prepend them to the next frame packet
                    config = payload
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
                for frame in frames:
                    self._publish(frame)
        except (EOFError, OSError) as e:
            self.error = e
        finally:
            if self.on_eof:
                self.on_eof()

    def _publish(self, frame):
        native = (frame.width, frame.height)
        target = self.target_size or native
        tw, th = max(2, int(target[0])), max(2, int(target[1]))
        rgb = frame.reformat(width=tw, height=th, format="rgb24",
                             interpolation="BILINEAR").to_ndarray()
        with self._lock:
            self.frame_size = native
            self._latest = (native, (tw, th), rgb.tobytes())
            self.frame_count += 1


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

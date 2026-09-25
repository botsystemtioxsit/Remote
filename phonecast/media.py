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
MAX_LAG_US = 300_000
# The "no lag" reference slowly follows the observed delay, so a steady extra
# delay of the link is absorbed while a growing backlog (much faster) is not.
BASE_DRIFT = 0.02          # 20 ms per second
WARMUP_S = 2.0             # startup hiccups (window creation...) are not backlog
KEYFRAME_RETRY_S = 1.5     # ask again if the requested keyframe does not come


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
        self.lag_ms = 0             # how far behind the phone the last packet was
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
        base = None          # (arrival time - pts) when not lagging: reference
        base_t = 0.0
        started = 0.0
        skipping = False     # waiting for a keyframe after falling behind
        requested = 0.0
        try:
            while True:
                pts, is_config, key, payload = read_packet(self.sock)
                if is_config:
                    # SPS/PPS: prepend them to the next frame packet. A new
                    # config means a new encoder session: its pts restart.
                    config = payload
                    base = None
                    continue

                now = time.monotonic()
                d = now * 1e6 - pts
                if base is None:
                    base, base_t, started = d, now, now
                base += (now - base_t) * 1e6 * BASE_DRIFT
                base_t = now
                base = min(base, d)
                self.lag_ms = int((d - base) / 1000)
                if skipping:
                    if not key:
                        if now - requested > KEYFRAME_RETRY_S and self.request_keyframe:
                            requested = now
                            self.request_keyframe()
                        continue
                    skipping = False
                    base = d  # resynced: this is the new reference
                elif d - base > MAX_LAG_US and not key and now - started > WARMUP_S:
                    skipping = True
                    self.drop_count += 1
                    if self.request_keyframe:
                        requested = now
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
    """Plays the phone audio: Opus (decoded here) or raw PCM, 48 kHz stereo."""

    def __init__(self, sock, command, codec="opus"):
        super().__init__(daemon=True, name="audio")
        self.sock = sock
        self.command = command
        self.codec = codec
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
        decoder = None
        resampler = av.AudioResampler(format="s16", layout="stereo", rate=48000)
        try:
            while True:
                _pts, is_config, _key, payload = read_packet(self.sock)
                if is_config:
                    if self.codec == "opus":
                        # OpusHead: the decoder's extradata
                        decoder = av.CodecContext.create("opus", "r")
                        decoder.extradata = payload
                    continue
                if self.codec == "opus":
                    if decoder is None:
                        continue
                    try:
                        frames = decoder.decode(av.Packet(payload))
                    except av.error.FFmpegError:
                        continue
                    payload = b"".join(bytes(r.planes[0])[: r.samples * 4]
                                       for f in frames for r in resampler.resample(f))
                    if not payload:
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

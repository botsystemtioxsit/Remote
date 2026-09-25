"""Starts scrcpy-server on the phone and speaks its socket protocol.

We reuse the official scrcpy server (a tiny Java program run through
app_process, no app install needed). It captures the screen with the hardware
H.264 encoder, captures audio (Android 11+), and injects touch/key events.
The desktop side (decoding, window, key mapping) is ours.
"""

import hashlib
import os
import random
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request

SERVER_VERSION = "3.3.4"
SERVER_SHA256 = "8588238c9a5a00aa542906b6ec7e6d5541d9ffb9b5d0f6e1bc0e365e2303079e"
SERVER_URL = ("https://github.com/Genymobile/scrcpy/releases/download/"
              "v{0}/scrcpy-server-v{0}".format(SERVER_VERSION))
DEVICE_SERVER_PATH = "/data/local/tmp/phonecast-server.jar"

CODEC_H264 = 0x68323634  # "h264"
CODEC_RAW = 0x00726177   # "raw"
CODEC_OPUS = 0x6F707573  # "opus"

PACKET_FLAG_CONFIG = 1 << 63
PACKET_FLAG_KEY_FRAME = 1 << 62
PTS_MASK = PACKET_FLAG_KEY_FRAME - 1


class SessionError(RuntimeError):
    pass


def data_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "phonecast")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_server_file(explicit_path=None):
    """Returns a local path to scrcpy-server, downloading it if needed."""
    if explicit_path:
        if not os.path.isfile(explicit_path):
            raise SessionError("server file not found: %s" % explicit_path)
        return explicit_path
    path = os.path.join(data_dir(), "scrcpy-server-v%s" % SERVER_VERSION)
    if os.path.isfile(path) and _sha256(path) == SERVER_SHA256:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print("phonecast: downloading scrcpy-server v%s ..." % SERVER_VERSION, file=sys.stderr)
    tmp = path + ".part"
    try:
        with urllib.request.urlopen(SERVER_URL, timeout=60) as r, open(tmp, "wb") as f:
            f.write(r.read())
    except OSError as e:
        raise SessionError("could not download %s: %s\n"
                           "Download it manually and pass --server-file PATH." % (SERVER_URL, e))
    if _sha256(tmp) != SERVER_SHA256:
        os.remove(tmp)
        raise SessionError("checksum mismatch for downloaded scrcpy-server")
    os.replace(tmp, path)
    return path


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("connection closed")
        buf += chunk
    return bytes(buf)


def read_packet(sock):
    """Returns (pts, is_config, is_key_frame, payload)."""
    header = recv_exact(sock, 12)
    pts_flags, size = struct.unpack(">QI", header)
    payload = recv_exact(sock, size)
    return (pts_flags & PTS_MASK, bool(pts_flags & PACKET_FLAG_CONFIG),
            bool(pts_flags & PACKET_FLAG_KEY_FRAME), payload)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Session:
    """A running mirroring session: video socket, optional audio, control."""

    def __init__(self, adb, max_size=1600, bit_rate=8_000_000, max_fps=60, audio=True,
                 server_file=None, stay_awake=True, verbose=False):
        self.adb = adb
        self.max_size = max_size
        self.bit_rate = bit_rate
        self.max_fps = max_fps
        self.want_audio = audio
        self.server_file = server_file
        self.stay_awake = stay_awake
        self.verbose = verbose

        self.device_name = ""
        self.initial_size = (0, 0)
        self.video_sock = None
        self.audio_sock = None
        self.control_sock = None
        self.audio_codec = None
        self._server = None
        self._send_lock = threading.Lock()
        self.closed = False

    # ----- lifecycle -----------------------------------------------------

    def start(self):
        server = ensure_server_file(self.server_file)
        self.adb.push(server, DEVICE_SERVER_PATH)

        scid = random.randint(0, 0x7FFFFFFF)
        socket_name = "scrcpy_%08x" % scid
        port = _free_port()
        self.adb.forward(port, "localabstract:" + socket_name)
        try:
            args = [
                "CLASSPATH=" + DEVICE_SERVER_PATH, "app_process", "/",
                "com.genymobile.scrcpy.Server", SERVER_VERSION,
                "scid=%08x" % scid,
                "log_level=" + ("debug" if self.verbose else "info"),
                "tunnel_forward=true",
                "video_codec=h264",
                "max_size=%d" % self.max_size,
                "video_bit_rate=%d" % self.bit_rate,
                "max_fps=%d" % self.max_fps,
                "audio=%s" % ("true" if self.want_audio else "false"),
                # Opus: ~0.13 Mbit/s instead of 1.5 Mbit/s for raw PCM, leaving
                # the USB link to the video.
                "audio_codec=opus",
                "control=true",
                "stay_awake=%s" % ("true" if self.stay_awake else "false"),
                "clipboard_autosync=false",
            ]
            self._server = self.adb.popen("shell", *args, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, text=True, errors="replace")
            threading.Thread(target=self._pipe_server_log, daemon=True).start()

            self.video_sock = self._connect_first(port)
            if self.want_audio:
                self.audio_sock = self._connect(port)
            self.control_sock = self._connect(port)
        finally:
            # Once connected, the tunnel is no longer needed.
            self.adb.forward_remove(port)

        name = recv_exact(self.video_sock, 64)
        self.device_name = name.split(b"\0", 1)[0].decode("utf-8", errors="replace")

        codec, w, h = struct.unpack(">III", recv_exact(self.video_sock, 12))
        if codec in (0, 1):
            raise SessionError("the device could not start video capture (see log above)")
        if codec != CODEC_H264:
            raise SessionError("unexpected video codec 0x%08x" % codec)
        self.initial_size = (w, h)

        if self.audio_sock:
            (acodec,) = struct.unpack(">I", recv_exact(self.audio_sock, 4))
            if acodec in (CODEC_OPUS, CODEC_RAW):
                self.audio_codec = "opus" if acodec == CODEC_OPUS else "raw"
            else:
                # 0: audio unavailable (Android < 11 or capture refused); continue without it.
                self.audio_sock.close()
                self.audio_sock = None
                if acodec == 1:
                    raise SessionError("audio configuration error")
        return self

    def _pipe_server_log(self):
        for line in self._server.stdout:
            line = line.rstrip()
            if line:
                print("[phone] " + line, file=sys.stderr)

    def _connect(self, port):
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Blocking mode: the video stream may legitimately be silent for a long
        # time when the phone screen does not change.
        s.settimeout(None)
        return s

    def _connect_first(self, port):
        # With `adb forward`, adb accepts the TCP connection even before the
        # server listens on the device; the server writes one dummy byte once
        # it has really accepted, so retry until we receive it.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._server.poll() is not None:
                raise SessionError("scrcpy-server exited (see log above)")
            try:
                s = self._connect(port)
                s.settimeout(2)
                if s.recv(1) == b"\0":
                    s.settimeout(None)
                    return s
                s.close()
            except OSError:
                pass
            time.sleep(0.1)
        raise SessionError("timeout while connecting to the phone")

    def close(self):
        if self.closed:
            return
        self.closed = True
        for s in (self.video_sock, self.audio_sock, self.control_sock):
            if s:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                s.close()
        if self._server and self._server.poll() is None:
            self._server.terminate()
            try:
                self._server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._server.kill()

    # ----- control -------------------------------------------------------

    def send(self, message):
        if self.closed or not self.control_sock:
            return
        with self._send_lock:
            try:
                self.control_sock.sendall(message)
            except OSError:
                pass

    def drain_device_messages(self):
        """The device may send messages (clipboard, acks) on the control socket;
        read and drop them so its buffer never fills up."""
        try:
            while self.control_sock.recv(4096):
                pass
        except OSError:
            pass

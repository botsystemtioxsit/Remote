"""Encoding of scrcpy control messages (client -> device).

Byte layout matches scrcpy-server v3.3.4
(server/src/main/java/com/genymobile/scrcpy/control/ControlMessageReader.java).
All integers are big-endian.
"""

import struct

TYPE_INJECT_KEYCODE = 0
TYPE_INJECT_TEXT = 1
TYPE_INJECT_TOUCH_EVENT = 2
TYPE_INJECT_SCROLL_EVENT = 3
TYPE_BACK_OR_SCREEN_ON = 4
TYPE_EXPAND_NOTIFICATION_PANEL = 5
TYPE_EXPAND_SETTINGS_PANEL = 6
TYPE_COLLAPSE_PANELS = 7
TYPE_GET_CLIPBOARD = 8
TYPE_SET_CLIPBOARD = 9
TYPE_SET_DISPLAY_POWER = 10
TYPE_ROTATE_DEVICE = 11
TYPE_START_APP = 16
TYPE_RESET_VIDEO = 17

# android.view.MotionEvent actions
ACTION_DOWN = 0
ACTION_UP = 1
ACTION_MOVE = 2

# android.view.KeyEvent actions
KEY_DOWN = 0
KEY_UP = 1

INJECT_TEXT_MAX_LENGTH = 300


def _u16_fixed_point(value):
    """Float in [0, 1] -> u16 fixed point (1.0 is encoded as 0xffff)."""
    value = min(max(value, 0.0), 1.0)
    if value >= 1.0:
        return 0xFFFF
    return int(value * 0x10000)


def _i16_fixed_point(value):
    """Float in [-1, 1] -> i16 fixed point."""
    value = min(max(value, -1.0), 1.0)
    return max(-0x8000, min(0x7FFF, int(value * 0x8000)))


def inject_keycode(action, keycode, repeat=0, meta_state=0):
    return struct.pack(">BBiii", TYPE_INJECT_KEYCODE, action, keycode, repeat, meta_state)


def _truncate_utf8(text, max_bytes):
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return data
    data = data[:max_bytes]
    # Drop a partially cut multi-byte character at the end.
    return data.decode("utf-8", errors="ignore").encode("utf-8")


def inject_text(text):
    data = _truncate_utf8(text, INJECT_TEXT_MAX_LENGTH)
    return struct.pack(">BI", TYPE_INJECT_TEXT, len(data)) + data


def inject_touch(action, pointer_id, x, y, screen_w, screen_h, pressure=1.0,
                 action_button=0, buttons=0):
    """(x, y) are pixel coordinates in the video frame of size (screen_w, screen_h).

    The server ignores the event if (screen_w, screen_h) does not match the
    current video size, which protects against races during rotation.
    """
    if action == ACTION_UP:
        pressure = 0.0
    return struct.pack(
        ">BBqiiHHHii",
        TYPE_INJECT_TOUCH_EVENT, action, pointer_id,
        int(x), int(y), screen_w, screen_h,
        _u16_fixed_point(pressure), action_button, buttons,
    )


def inject_scroll(x, y, screen_w, screen_h, hscroll, vscroll, buttons=0):
    """hscroll/vscroll are in [-16, 16] (the server multiplies by 16)."""
    return struct.pack(
        ">BiiHHhhi",
        TYPE_INJECT_SCROLL_EVENT, int(x), int(y), screen_w, screen_h,
        _i16_fixed_point(hscroll / 16), _i16_fixed_point(vscroll / 16), buttons,
    )


def back_or_screen_on(action):
    return struct.pack(">BB", TYPE_BACK_OR_SCREEN_ON, action)


def expand_notification_panel():
    return struct.pack(">B", TYPE_EXPAND_NOTIFICATION_PANEL)


def expand_settings_panel():
    return struct.pack(">B", TYPE_EXPAND_SETTINGS_PANEL)


def collapse_panels():
    return struct.pack(">B", TYPE_COLLAPSE_PANELS)


def set_clipboard(text, paste, sequence=0):
    """sequence=0 means the device does not send an acknowledgement."""
    data = text.encode("utf-8")
    return struct.pack(">BqBI", TYPE_SET_CLIPBOARD, sequence, 1 if paste else 0, len(data)) + data


def set_display_power(on):
    return struct.pack(">BB", TYPE_SET_DISPLAY_POWER, 1 if on else 0)


def rotate_device():
    return struct.pack(">B", TYPE_ROTATE_DEVICE)


def start_app(name):
    data = _truncate_utf8(name, 255)
    return struct.pack(">BB", TYPE_START_APP, len(data)) + data


def reset_video():
    return struct.pack(">B", TYPE_RESET_VIDEO)

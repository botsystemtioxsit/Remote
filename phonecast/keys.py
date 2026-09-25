"""Key naming and Android keycodes.

Keys are identified by their physical position (USB HID / SDL scancode), not by
the character they produce. This way WASD works the same with the Russian
layout active, and profiles are portable between layouts.
"""

# SDL scancode -> key name used in profiles.
SCANCODE_NAMES = {}

for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    SCANCODE_NAMES[4 + _i] = _c
for _i, _c in enumerate("1234567890"):
    SCANCODE_NAMES[30 + _i] = _c
for _i in range(12):
    SCANCODE_NAMES[58 + _i] = "f%d" % (_i + 1)
for _i in range(9):
    SCANCODE_NAMES[89 + _i] = "kp%d" % (_i + 1)

SCANCODE_NAMES.update({
    40: "enter", 41: "escape", 42: "backspace", 43: "tab", 44: "space",
    45: "-", 46: "=", 47: "[", 48: "]", 49: "\\", 51: ";", 52: "'", 53: "`",
    54: ",", 55: ".", 56: "/", 57: "capslock",
    73: "insert", 74: "home", 75: "pageup", 76: "delete", 77: "end", 78: "pagedown",
    79: "right", 80: "left", 81: "down", 82: "up",
    84: "kp/", 85: "kp*", 86: "kp-", 87: "kp+", 88: "kpenter", 98: "kp0", 99: "kp.",
    224: "lctrl", 225: "lshift", 226: "lalt", 227: "lsuper",
    228: "rctrl", 229: "rshift", 230: "ralt", 231: "rsuper",
})

MOUSE_BUTTON_NAMES = {
    1: "mouse_left",
    2: "mouse_middle",
    3: "mouse_right",
    6: "mouse_x1",  # SDL2 via pygame reports side buttons as 6 and 7
    7: "mouse_x2",
}

# Keys reserved for the application itself (see HOTKEYS in app.py).
RESERVED = {"f%d" % i for i in range(1, 13)}

# Android KeyEvent keycodes.
KEYCODE_HOME = 3
KEYCODE_BACK = 4
KEYCODE_VOLUME_UP = 24
KEYCODE_VOLUME_DOWN = 25
KEYCODE_POWER = 26
KEYCODE_MENU = 82
KEYCODE_APP_SWITCH = 187
KEYCODE_VOLUME_MUTE = 164

ANDROID_KEYCODES = {}
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    ANDROID_KEYCODES[_c] = 29 + _i
for _i, _c in enumerate("0123456789"):
    ANDROID_KEYCODES[_c] = 7 + _i
for _i in range(12):
    ANDROID_KEYCODES["f%d" % (_i + 1)] = 131 + _i
for _i in range(10):
    ANDROID_KEYCODES["kp%d" % _i] = 144 + _i

ANDROID_KEYCODES.update({
    "enter": 66, "escape": 111, "backspace": 67, "tab": 61, "space": 62,
    "-": 69, "=": 70, "[": 71, "]": 72, "\\": 73, ";": 74, "'": 75, "`": 68,
    ",": 55, ".": 56, "/": 76, "capslock": 115,
    "insert": 124, "home": 122, "pageup": 92, "delete": 112, "end": 123, "pagedown": 93,
    "right": 22, "left": 21, "down": 20, "up": 19,
    "kp/": 154, "kp*": 155, "kp-": 156, "kp+": 157, "kpenter": 160, "kp.": 158,
    "lctrl": 113, "rctrl": 114, "lshift": 59, "rshift": 60, "lalt": 57, "ralt": 58,
    "lsuper": 117, "rsuper": 118,
})

# Named Android actions usable in profiles: {"type": "android", "action": "back"}.
ANDROID_ACTIONS = {
    "back": KEYCODE_BACK,
    "home": KEYCODE_HOME,
    "recents": KEYCODE_APP_SWITCH,
    "menu": KEYCODE_MENU,
    "power": KEYCODE_POWER,
    "volume_up": KEYCODE_VOLUME_UP,
    "volume_down": KEYCODE_VOLUME_DOWN,
    "mute": KEYCODE_VOLUME_MUTE,
}

# Keys that produce no text and must be sent as keycodes in normal (typing) mode.
NON_TEXT_KEYS = {
    "enter", "escape", "backspace", "tab", "insert", "home", "pageup", "delete",
    "end", "pagedown", "right", "left", "down", "up", "kpenter",
}

# android.view.KeyEvent meta state flags
META_SHIFT_ON = 0x1 | 0x40
META_ALT_ON = 0x2 | 0x10
META_CTRL_ON = 0x1000 | 0x2000


def key_name(scancode, fallback=None):
    return SCANCODE_NAMES.get(scancode, fallback)


def pretty(name):
    """Short label for drawing on the overlay."""
    labels = {
        "space": "Space", "lshift": "LShift", "rshift": "RShift", "lctrl": "LCtrl",
        "rctrl": "RCtrl", "lalt": "LAlt", "ralt": "RAlt", "enter": "Enter",
        "escape": "Esc", "backspace": "Bksp", "tab": "Tab", "capslock": "Caps",
        "mouse_left": "LMB", "mouse_right": "RMB", "mouse_middle": "MMB",
        "mouse_x1": "M4", "mouse_x2": "M5", "up": "Up", "down": "Down",
        "left": "Left", "right": "Right",
    }
    if name in labels:
        return labels[name]
    return name.upper() if len(name) <= 3 else name.capitalize()

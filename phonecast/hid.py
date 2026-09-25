"""Virtual USB keyboard and mouse for the phone (UHID).

The phone sees them as a real keyboard and mouse plugged into it, so games
with native keyboard/mouse support (e.g. Minecraft) switch to their PC
controls: WASD, mouse look with pointer capture, Esc for the menu...

Report descriptors and report layouts are the ones of the official scrcpy
client (app/src/hid/hid_keyboard.c and hid_mouse.c, v3.3.4).
"""

KEYBOARD_ID = 1
MOUSE_ID = 2

KEYBOARD_KEYS = 0x66  # HID usages 0x00..0x65 (plus the 8 modifiers)
KEYBOARD_MAX_KEYS = 6

KEYBOARD_REPORT_DESC = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x06,        # Usage (Keyboard)
    0xA1, 0x01,        # Collection (Application)
    0x05, 0x07,        #   Usage Page (Key Codes)
    0x19, 0xE0,        #   Usage Minimum (224)
    0x29, 0xE7,        #   Usage Maximum (231)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x08,        #   Report Count (8)
    0x81, 0x02,        #   Input (Data, Variable, Absolute): modifier byte
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x01,        #   Input (Constant): reserved byte
    0x05, 0x08,        #   Usage Page (LEDs)
    0x19, 0x01,        #   Usage Minimum (1)
    0x29, 0x05,        #   Usage Maximum (5)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x05,        #   Report Count (5)
    0x91, 0x02,        #   Output (Data, Variable, Absolute): LED report
    0x75, 0x03,        #   Report Size (3)
    0x95, 0x01,        #   Report Count (1)
    0x91, 0x01,        #   Output (Constant): LED padding
    0x05, 0x07,        #   Usage Page (Key Codes)
    0x19, 0x00,        #   Usage Minimum (0)
    0x29, KEYBOARD_KEYS - 1,
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, KEYBOARD_KEYS - 1,
    0x75, 0x08,        #   Report Size (8)
    0x95, KEYBOARD_MAX_KEYS,
    0x81, 0x00,        #   Input (Data, Array): keys
    0xC0,              # End Collection
])

MOUSE_REPORT_DESC = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x02,        # Usage (Mouse)
    0xA1, 0x01,        # Collection (Application)
    0x09, 0x01,        #   Usage (Pointer)
    0xA1, 0x00,        #   Collection (Physical)
    0x05, 0x09,        #     Usage Page (Buttons)
    0x19, 0x01,        #     Usage Minimum (1)
    0x29, 0x05,        #     Usage Maximum (5)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x95, 0x05,        #     Report Count (5)
    0x75, 0x01,        #     Report Size (1)
    0x81, 0x02,        #     Input (Data, Variable, Absolute): 5 buttons
    0x95, 0x01,        #     Report Count (1)
    0x75, 0x03,        #     Report Size (3)
    0x81, 0x01,        #     Input (Constant): padding
    0x05, 0x01,        #     Usage Page (Generic Desktop)
    0x09, 0x30,        #     Usage (X)
    0x09, 0x31,        #     Usage (Y)
    0x09, 0x38,        #     Usage (Wheel)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x03,        #     Report Count (3)
    0x81, 0x06,        #     Input (Data, Variable, Relative)
    0x05, 0x0C,        #     Usage Page (Consumer)
    0x0A, 0x38, 0x02,  #     Usage (AC Pan): horizontal wheel
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x06,        #     Input (Data, Variable, Relative)
    0xC0,              #   End Collection
    0xC0,              # End Collection
])

# pygame mouse button number -> HID button bit
MOUSE_BUTTON_BITS = {1: 0, 3: 1, 2: 2, 6: 3, 7: 4}


def _i8(v):
    return max(-127, min(127, int(v))) & 0xFF


class Keyboard:
    """Tracks pressed keys and builds 8-byte boot keyboard reports.

    Keys are USB HID usage ids, which are exactly SDL/pygame scancodes.
    """

    def __init__(self):
        self.mods = 0
        self.keys = []  # in press order

    def press(self, scancode):
        """Returns the report to send, or None if nothing changed."""
        if 0xE0 <= scancode <= 0xE7:
            bit = 1 << (scancode - 0xE0)
            if self.mods & bit:
                return None
            self.mods |= bit
        elif 0 < scancode < KEYBOARD_KEYS:
            if scancode in self.keys:
                return None
            self.keys.append(scancode)
        else:
            return None
        return self.report()

    def release(self, scancode):
        if 0xE0 <= scancode <= 0xE7:
            bit = 1 << (scancode - 0xE0)
            if not self.mods & bit:
                return None
            self.mods &= ~bit
        elif scancode in self.keys:
            self.keys.remove(scancode)
        else:
            return None
        return self.report()

    def release_all(self):
        if not self.mods and not self.keys:
            return None
        self.mods = 0
        self.keys = []
        return self.report()

    def report(self):
        if len(self.keys) > KEYBOARD_MAX_KEYS:
            keys = [0x01] * KEYBOARD_MAX_KEYS  # "error roll over"
        else:
            keys = self.keys + [0] * (KEYBOARD_MAX_KEYS - len(self.keys))
        return bytes([self.mods, 0] + keys)


class Mouse:
    """Relative mouse: builds 5-byte reports (buttons, dx, dy, wheel, hwheel)."""

    def __init__(self):
        self.buttons = 0

    def button(self, pygame_button, down):
        bit = MOUSE_BUTTON_BITS.get(pygame_button)
        if bit is None:
            return None
        new = (self.buttons | (1 << bit)) if down else (self.buttons & ~(1 << bit))
        if new == self.buttons:
            return None
        self.buttons = new
        return self._report()

    def motion(self, dx, dy):
        """A large motion is split into several reports of at most 127."""
        reports = []
        dx, dy = int(dx), int(dy)
        while dx or dy:
            sx = max(-127, min(127, dx))
            sy = max(-127, min(127, dy))
            reports.append(self._report(sx, sy))
            dx -= sx
            dy -= sy
        return reports

    def wheel(self, v, h=0):
        if not v and not h:
            return None
        return self._report(0, 0, v, h)

    def release_all(self):
        if not self.buttons:
            return None
        self.buttons = 0
        return self._report()

    def _report(self, dx=0, dy=0, wheel=0, hwheel=0):
        return bytes([self.buttons, _i8(dx), _i8(dy), _i8(wheel), _i8(hwheel)])

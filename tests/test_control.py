import struct
import unittest

from phonecast import control


class ControlMessageTest(unittest.TestCase):
    def test_touch_layout(self):
        msg = control.inject_touch(control.ACTION_DOWN, 7, 100, 200, 1080, 2400)
        self.assertEqual(len(msg), 32)
        t, action, pid, x, y, w, h, pressure, ab, buttons = struct.unpack(">BBqiiHHHii", msg)
        self.assertEqual((t, action, pid, x, y, w, h), (2, 0, 7, 100, 200, 1080, 2400))
        self.assertEqual(pressure, 0xFFFF)
        self.assertEqual((ab, buttons), (0, 0))

    def test_touch_up_has_zero_pressure(self):
        msg = control.inject_touch(control.ACTION_UP, 1, 0, 0, 10, 10)
        self.assertEqual(struct.unpack(">H", msg[22:24])[0], 0)

    def test_keycode_layout(self):
        msg = control.inject_keycode(control.KEY_UP, 4, 0, 0x1000)
        self.assertEqual(msg, struct.pack(">BBiii", 0, 1, 4, 0, 0x1000))
        self.assertEqual(len(msg), 14)

    def test_text_is_utf8_and_truncated_on_char_boundary(self):
        msg = control.inject_text("привет")
        self.assertEqual(msg[0], 1)
        (n,) = struct.unpack(">I", msg[1:5])
        self.assertEqual(msg[5:].decode("utf-8"), "привет")
        self.assertEqual(n, len("привет".encode("utf-8")))
        long_msg = control.inject_text("ж" * 400)  # 2 bytes each
        (n,) = struct.unpack(">I", long_msg[1:5])
        self.assertLessEqual(n, control.INJECT_TEXT_MAX_LENGTH)
        long_msg[5:].decode("utf-8")  # must not raise

    def test_scroll(self):
        msg = control.inject_scroll(5, 6, 100, 200, 0, 1)
        self.assertEqual(len(msg), 21)
        t, x, y, w, h, hs, vs, b = struct.unpack(">BiiHHhhi", msg)
        self.assertEqual((t, x, y, w, h, hs, b), (3, 5, 6, 100, 200, 0, 0))
        self.assertEqual(vs, 0x8000 // 16)

    def test_clipboard(self):
        msg = control.set_clipboard("hi", paste=True)
        self.assertEqual(msg, struct.pack(">BqBI", 9, 0, 1, 2) + b"hi")

    def test_simple(self):
        self.assertEqual(control.set_display_power(False), b"\x0a\x00")
        self.assertEqual(control.rotate_device(), b"\x0b")
        self.assertEqual(control.back_or_screen_on(1), b"\x04\x01")


if __name__ == "__main__":
    unittest.main()

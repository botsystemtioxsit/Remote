import struct
import unittest

from phonecast import control, hid


class HidTest(unittest.TestCase):
    def test_keyboard_reports(self):
        k = hid.Keyboard()
        self.assertEqual(k.press(4), bytes([0, 0, 4, 0, 0, 0, 0, 0]))     # a
        self.assertIsNone(k.press(4))                                    # already down
        self.assertEqual(k.press(0xE1), bytes([2, 0, 4, 0, 0, 0, 0, 0]))  # + left shift
        self.assertEqual(k.release(4), bytes([2, 0, 0, 0, 0, 0, 0, 0]))
        self.assertIsNone(k.release(4))
        self.assertIsNone(k.press(0x80))                                 # outside the descriptor
        self.assertEqual(k.release_all(), bytes(8))
        self.assertIsNone(k.release_all())

    def test_keyboard_rollover(self):
        k = hid.Keyboard()
        for sc in range(4, 11):
            report = k.press(sc)
        self.assertEqual(report, bytes([0, 0] + [1] * 6))
        self.assertEqual(k.release(10), bytes([0, 0, 4, 5, 6, 7, 8, 9]))

    def test_mouse_reports(self):
        m = hid.Mouse()
        self.assertEqual(m.motion(0, 0), [])
        self.assertEqual(m.motion(-300, 10), [bytes([0, 0x81, 10, 0, 0]),
                                              bytes([0, 0x81, 0, 0, 0]),
                                              bytes([0, 0xD2, 0, 0, 0])])
        self.assertEqual(m.button(3, True), bytes([2, 0, 0, 0, 0]))     # right
        self.assertEqual(m.motion(1, 1), [bytes([2, 1, 1, 0, 0])])     # buttons kept while moving
        self.assertIsNone(m.button(3, True))
        self.assertIsNone(m.button(4, True))                          # unknown button
        self.assertEqual(m.wheel(1), bytes([2, 0, 0, 1, 0]))
        self.assertEqual(m.release_all(), bytes(5))

    def test_uhid_messages(self):
        msg = control.uhid_create(2, hid.MOUSE_REPORT_DESC, "Mouse")
        self.assertEqual(msg[:8], struct.pack(">BHHHB", 12, 2, 0, 0, 5))
        self.assertEqual(msg[8:13], b"Mouse")
        self.assertEqual(struct.unpack(">H", msg[13:15])[0], len(hid.MOUSE_REPORT_DESC))
        self.assertEqual(msg[15:], hid.MOUSE_REPORT_DESC)
        self.assertEqual(control.uhid_input(1, b"\x01\x02"), bytes([13, 0, 1, 0, 2, 1, 2]))
        self.assertEqual(control.uhid_destroy(1), bytes([14, 0, 1]))


if __name__ == "__main__":
    unittest.main()

"""End-to-end: fake adb + fake phone (real scrcpy protocol, real H.264), real app, headless."""

import os
import stat
import struct
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def parse_control(data):
    msgs = []
    i = 0
    while i < len(data):
        t = data[i]
        if t == 0:
            _, action, code, _r, meta = struct.unpack(">BBiii", data[i:i + 14])
            msgs.append(("key", action, code, meta))
            i += 14
        elif t == 1:
            (n,) = struct.unpack(">I", data[i + 1:i + 5])
            msgs.append(("text", data[i + 5:i + 5 + n].decode()))
            i += 5 + n
        elif t == 2:
            f = struct.unpack(">BBqiiHHHii", data[i:i + 32])
            msgs.append(("touch", f[1], f[2], f[3], f[4], f[5], f[6]))
            i += 32
        elif t == 3:
            msgs.append(("scroll",))
            i += 21
        elif t in (4, 10):
            msgs.append(("msg%d" % t, data[i + 1]))
            i += 2
        elif t == 9:
            (n,) = struct.unpack(">I", data[i + 10:i + 14])
            msgs.append(("clipboard", data[i + 14:i + 14 + n].decode()))
            i += 14 + n
        elif t == 12:
            hid_id, _v, _p, n = struct.unpack(">HHHB", data[i + 1:i + 8])
            name = data[i + 8:i + 8 + n].decode()
            (dl,) = struct.unpack(">H", data[i + 8 + n:i + 10 + n])
            msgs.append(("uhid_create", hid_id, name, dl))
            i += 10 + n + dl
        elif t == 13:
            hid_id, n = struct.unpack(">HH", data[i + 1:i + 5])
            msgs.append(("uhid_input", hid_id, data[i + 5:i + 5 + n]))
            i += 5 + n
        elif t == 14:
            msgs.append(("uhid_destroy", struct.unpack(">H", data[i + 1:i + 3])[0]))
            i += 3
        elif t in (5, 6, 7, 11, 15, 17):
            msgs.append(("msg%d" % t,))
            i += 1
        else:
            raise AssertionError("unknown control message type %d at %d" % (t, i))
    return msgs


@unittest.skipUnless(sys.platform.startswith("linux"), "linux only")
class EndToEndTest(unittest.TestCase):
    def test_full_session(self):
        tmp = tempfile.mkdtemp()
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        adb = os.path.join(bindir, "adb")
        with open(adb, "w") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, os.path.join(HERE, "fake_adb.py")))
        os.chmod(adb, os.stat(adb).st_mode | stat.S_IEXEC)
        os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
        os.environ["FAKE_ADB_DIR"] = tmp
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        server_file = os.path.join(tmp, "server.jar")
        open(server_file, "wb").close()

        import pygame
        from phonecast.adb import Adb
        from phonecast.app import App
        from phonecast.keymap import Profile
        from phonecast.session import Session

        profiles_dir = os.path.join(tmp, "profiles")
        game = Profile("Game", [
            {"type": "tap", "key": "space", "x": 0.5, "y": 0.5},
            {"type": "joystick", "x": 0.25, "y": 0.5, "radius": 0.2,
             "up": "w", "left": "a", "down": "s", "right": "d"},
            {"type": "aim", "toggle": "`", "x": 0.75, "y": 0.5, "radius": 0.3},
            {"type": "tap", "key": "mouse_left", "x": 0.9, "y": 0.9},
        ], ["com.test.game"], os.path.join(profiles_dir, "game.json"))

        a = Adb()
        self.assertEqual(a.select_device(), "FAKE123")
        session = Session(a, audio=True, server_file=server_file).start()
        self.assertEqual(session.device_name, "Fake Phone")
        self.assertEqual(session.initial_size, (640, 360))
        self.assertEqual(session.audio_codec, "opus")

        app = App(session, a, [], profiles_dir, mouse_sensitivity=1.0)
        seen = {"rotated": False, "landscape_again": False}


        def key(sc, down=True):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN if down else pygame.KEYUP,
                                                 key=0, scancode=sc, mod=0, unicode=""))

        def phase_normal():
            c = app.view.center
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=c))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=c))
            pygame.event.post(pygame.event.Event(pygame.TEXTINPUT, text="привет"))
            key(40)  # enter -> keycode
            key(40, False)

        def phase_profile():
            app.profiles.append(game)  # foreground watcher will pick it up
            app._fg_seen = None

        def phase_game():
            key(44)            # space -> tap at center
            key(44, False)
            key(26)            # w -> joystick up
            key(26, False)
            key(53)            # ` -> aim on
            pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=(0, 0), rel=(40, 0), buttons=(0, 0, 0)))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(0, 0)))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
            key(53)            # aim off

        def click(pos, button=1):
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=button, pos=pos))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=button, pos=pos))

        def phase_editor_open():
            key(60)  # F3

        def phase_editor_place():
            # drag "Кнопка (нажатие)" from the panel onto the screen, then press Q
            self.assertGreater(app.screen.get_width(), app.view.right + 200)  # panel beside
            src = app.editor._buttons[0][0].center
            dst = app.norm_to_window(0.1, 0.1)
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=src))
            pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=dst, rel=(0, 0), buttons=(1, 0, 0)))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=dst))
            key(20)  # q

        def phase_editor_rebind():
            # click the "Space" label, press X: the tap moves from Space to X
            rect = next(r for r, i, role in app.editor._labels
                        if app.profile.mappings[i].get("key") == "space")
            click(rect.center)
            key(27)  # x

        def phase_editor_save():
            save = next(rect for rect, _a, caption in app.editor._buttons if caption == "Сохранить")
            click(save.center)

        def phase_alt_to_menu():
            key(226)            # left Alt pressed and released alone
            key(226, False)

        def phase_menu_click():
            self.assertFalse(app.keymap_on)
            click(app.norm_to_window(0.3, 0.3))  # a normal touch in the game menu
            key(226)
            key(226, False)     # back to battle

        def phase_pc_on():
            key(69)  # F12 -> PC mode

        def phase_pc_play():
            key(26)            # w (HID usage 0x1a)
            key(225)           # left shift
            key(26, False)
            key(225, False)
            pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=(0, 0), rel=(200, -3), buttons=(0, 0, 0)))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(0, 0)))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
            pygame.event.post(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1, flipped=False))
            key(58)            # F1 must go to the phone in PC mode, not show our help
            key(58, False)

        def phase_pc_off():
            self.assertFalse(app.show_help)
            key(69)  # F12 -> back

        steps = [
            (lambda: app.frame_surface is not None, phase_normal),
            (lambda: True, phase_profile),
            (lambda: app.keymap_on, phase_game),
            (lambda: not app.engine.aim_active and app.grabbed is False, phase_editor_open),
            (lambda: app.editor is not None and app.editor._buttons, phase_editor_place),
            (lambda: any(m.get("key") == "q" for m in app.profile.mappings) and app.editor.capture is None
             and app.editor._labels, phase_editor_rebind),
            (lambda: any(m.get("key") == "x" for m in app.profile.mappings), phase_editor_save),
            (lambda: app.editor is None and app.keymap_on and app.view.right >= app.screen.get_width() - 1,
             phase_alt_to_menu),
            (lambda: app.menu_mode, phase_menu_click),
            (lambda: app.keymap_on, lambda: None),
            (lambda: app.editor is None, phase_pc_on),
            (lambda: app.pc_mode and app.grabbed, phase_pc_play),
            (lambda: True, phase_pc_off),
            (lambda: seen["landscape_again"] and not app.pc_mode, lambda: setattr(app, "running", False)),
        ]
        deadline = time.monotonic() + 30
        orig_poll = app._poll_foreground

        def hook():
            orig_poll()
            if app.frame_native == (360, 640):
                seen["rotated"] = True
                self.assertEqual(app.view.w < app.view.h, True)
            elif seen["rotated"] and app.frame_native == (640, 360):
                seen["landscape_again"] = True
            if steps and steps[0][0]():
                steps.pop(0)[1]()
            if time.monotonic() > deadline:
                app.running = False

        app._poll_foreground = hook
        try:
            app.run()
        finally:
            session.close()

        self.assertEqual(steps, [], "scenario did not finish")
        self.assertTrue(seen["rotated"])
        self.assertGreater(app.decoder.frame_count, 60)

        time.sleep(0.3)
        with open(os.path.join(tmp, "control.bin"), "rb") as f:
            msgs = parse_control(f.read())
        touches = [m for m in msgs if m[0] == "touch"]

        # Mouse click at the center of the 640x360 video, pointer 0
        self.assertIn(("touch", 0, 0, 320, 180, 640, 360), touches)
        self.assertIn(("touch", 1, 0, 320, 180, 640, 360), touches)
        self.assertIn(("text", "привет"), msgs)
        self.assertIn(("key", 0, 66, 0), msgs)  # enter down
        # Space mapped to (0.5, 0.5)
        self.assertIn(("touch", 0, 300, 320, 180, 640, 360), touches)
        # Joystick up: from (160, 180) towards y = 180 - 0.2*360 = 108
        self.assertIn(("touch", 2, 201, 160, 108, 640, 360), touches)
        # Aim finger went down at (480, 180) and moved right
        aim = [m for m in touches if m[2] == 100]
        self.assertEqual(aim[0][1:4], (0, 100, 480))
        self.assertGreater(aim[1][3], 480)
        self.assertEqual(aim[-1][1], 1)
        # mouse_left in aim mode fires the mapped button at (0.9, 0.9)
        self.assertIn(("touch", 0, 303, 576, 324, 640, 360), touches)
        # Every finger that went down came back up
        down = {m[2] for m in touches if m[1] == 0}
        up = {m[2] for m in touches if m[1] == 1}
        self.assertEqual(down, up)

        # PC mode: virtual keyboard + mouse created, used, destroyed
        self.assertIn(("uhid_create", 1, "Phonecast Keyboard", 63), msgs)
        self.assertIn(("uhid_create", 2, "Phonecast Mouse", 67), msgs)
        hid_in = [(m[1], m[2]) for m in msgs if m[0] == "uhid_input"]
        kb = [d for i, d in hid_in if i == 1]
        mouse = [d for i, d in hid_in if i == 2]
        self.assertEqual(kb[:4], [bytes([0, 0, 0x1a, 0, 0, 0, 0, 0]), bytes([2, 0, 0x1a, 0, 0, 0, 0, 0]),
                                  bytes([2, 0, 0, 0, 0, 0, 0, 0]), bytes(8)])
        self.assertIn(bytes([0, 0, 0x3a, 0, 0, 0, 0, 0]), kb)  # F1 went to the phone
        self.assertEqual(mouse[0], bytes([0, 127, 0xFD, 0, 0]))  # 200 px split: 127 + 73
        self.assertEqual(mouse[1], bytes([0, 73, 0, 0, 0]))
        self.assertIn(bytes([1, 0, 0, 0, 0]), mouse)            # left button down
        self.assertIn(bytes([0, 0, 0, 0xFF, 0]), mouse)         # wheel -1
        self.assertEqual([m for m in msgs if m[0] == "uhid_destroy"], [("uhid_destroy", 1), ("uhid_destroy", 2)])

        # Editor bound Q at (0.1, 0.1) and saved the profile
        saved = Profile.load(game.path)
        self.assertIn({"type": "tap", "key": "x", "x": 0.5, "y": 0.5}, saved.mappings)
        self.assertFalse(any(m.get("key") == "space" for m in saved.mappings))
        # In menu mode (Alt) the click at (0.3, 0.3) went to the phone as a normal touch
        self.assertTrue(any(m[1:3] == (0, 0) and abs(m[3] - 192) <= 1 and abs(m[4] - 108) <= 1
                            for m in touches))
        q = [m for m in saved.mappings if m.get("key") == "q"]
        self.assertEqual(len(q), 1)
        self.assertAlmostEqual(q[0]["x"], 0.1, delta=0.01)
        self.assertAlmostEqual(q[0]["y"], 0.1, delta=0.01)


if __name__ == "__main__":
    unittest.main()

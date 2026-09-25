"""Mouse routing in game mode, without a window."""

import os
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from phonecast import __main__ as cli  # noqa: E402
from phonecast import control  # noqa: E402
from phonecast.app import App  # noqa: E402
from phonecast.keymap import Profile  # noqa: E402


class FakeSession:
    device_name = "Fake"

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


class FakeDecoder:
    frame_size = (1000, 500)


def make_app(mappings):
    pygame.display.init()
    session = FakeSession()
    app = App(session, None, [Profile("p", mappings)], "/nonexistent")
    app.decoder = FakeDecoder()
    app.frame_native = (1000, 500)
    app.view = pygame.Rect(0, 0, 1000, 500)
    app.keymap_on = True
    return app, session


def touches(session):
    import struct
    out = []
    for m in session.sent:
        if m[0] == control.TYPE_INJECT_TOUCH_EVENT:
            f = struct.unpack(">BBqiiHHHii", m)
            out.append((f[1], f[2], f[3], f[4]))
    return out


class Ev:
    def __init__(self, button, pos):
        self.button, self.pos = button, pos


class MouseRoutingTest(unittest.TestCase):
    def test_left_button_fires_skill_towards_cursor(self):
        app, s = make_app([{"type": "skill", "key": "mouse_left", "x": 0.8, "y": 0.7,
                            "radius": 0.1, "origin": [0.5, 0.5], "range": 0.35}])
        app._mouse_button(Ev(1, (900, 250)), True)   # cursor right of the character
        app._mouse_button(Ev(1, (900, 250)), False)
        t = touches(s)
        self.assertEqual(t[0], (0, 300, 800, 350))   # finger down on the attack button
        self.assertEqual(t[-1][0:2], (1, 300))       # released: fires
        self.assertGreater(t[-1][2], 800)            # ...after being dragged to the right

    def test_left_button_stays_a_normal_touch_for_taps_without_aim(self):
        app, s = make_app([{"type": "tap", "key": "mouse_left", "x": 0.9, "y": 0.9},
                           {"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5}])
        app._mouse_button(Ev(1, (100, 100)), True)
        app._mouse_button(Ev(1, (100, 100)), False)
        self.assertEqual(touches(s), [(0, 0, 100, 100), (1, 0, 100, 100)])

    def test_auto_aim_captures_mouse_when_mapping_is_enabled(self):
        app, _ = make_app([{"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5, "auto": True}])
        app.keymap_on = False
        app.set_keymap(True)
        self.assertTrue(app.engine.aim_active)


class SeedProfilesTest(unittest.TestCase):
    def test_new_bundled_profiles_arrive_deleted_ones_stay_deleted(self):
        with tempfile.TemporaryDirectory() as bundled, tempfile.TemporaryDirectory() as home:
            user = os.path.join(home, "profiles")
            orig = cli.bundled_profiles_dir
            cli.bundled_profiles_dir = lambda: bundled
            try:
                for name in ("a.json", "b.json"):
                    open(os.path.join(bundled, name), "w").write("{}")
                cli.seed_profiles(user)
                self.assertEqual(sorted(f for f in os.listdir(user) if f.endswith(".json")),
                                 ["a.json", "b.json"])
                os.remove(os.path.join(user, "a.json"))         # the user deleted one
                open(os.path.join(user, "b.json"), "w").write('{"edited": 1}')
                open(os.path.join(bundled, "c.json"), "w").write("{}")  # update adds one
                cli.seed_profiles(user)
                self.assertEqual(sorted(f for f in os.listdir(user) if f.endswith(".json")),
                                 ["b.json", "c.json"])
                self.assertEqual(open(os.path.join(user, "b.json")).read(), '{"edited": 1}')
            finally:
                cli.bundled_profiles_dir = orig

    def test_existing_install_without_record_gets_only_new_profiles(self):
        with tempfile.TemporaryDirectory() as bundled, tempfile.TemporaryDirectory() as user:
            orig = cli.bundled_profiles_dir
            cli.bundled_profiles_dir = lambda: bundled
            try:
                for name in ("shooter.json", "standoff2.json"):
                    open(os.path.join(bundled, name), "w").write("{}")
                open(os.path.join(user, "shooter.json"), "w").write('{"mine": 1}')
                cli.seed_profiles(user)
                self.assertTrue(os.path.exists(os.path.join(user, "standoff2.json")))
                self.assertEqual(open(os.path.join(user, "shooter.json")).read(), '{"mine": 1}')
            finally:
                cli.bundled_profiles_dir = orig


if __name__ == "__main__":
    unittest.main()

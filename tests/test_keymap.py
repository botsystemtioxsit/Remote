import os
import tempfile
import unittest

from phonecast import control
from phonecast.keymap import AIM_POINTER_ID, Engine, Profile, load_profiles

DOWN, UP, MOVE = control.ACTION_DOWN, control.ACTION_UP, control.ACTION_MOVE


def make_engine(mappings, aspect=2.0):
    touches, keycodes = [], []
    engine = Engine(lambda a, p, x, y: touches.append((a, p, round(x, 4), round(y, 4))),
                    keycodes.append, lambda: aspect)
    engine.set_profile(Profile("t", mappings))
    return engine, touches, keycodes


class EngineTest(unittest.TestCase):
    def test_tap_hold_and_release(self):
        e, t, _ = make_engine([{"type": "tap", "key": "space", "x": 0.9, "y": 0.8}])
        self.assertTrue(e.key_down("space"))
        self.assertTrue(e.key_down("space"))  # repeat does not press twice
        self.assertTrue(e.key_up("space"))
        self.assertEqual(t, [(DOWN, 300, 0.9, 0.8), (UP, 300, 0.9, 0.8)])
        self.assertFalse(e.key_down("x"))

    def test_joystick_directions_and_release(self):
        e, t, _ = make_engine([{"type": "joystick", "x": 0.2, "y": 0.7, "radius": 0.1,
                                "up": "w", "left": "a", "down": "s", "right": "d"}])
        e.key_down("w")
        self.assertEqual(t[0], (DOWN, 200, 0.2, 0.7))
        self.assertEqual(t[-1], (MOVE, 200, 0.2, 0.6))
        e.key_down("d")  # diagonal, x offset divided by aspect ratio
        a, p, x, y = t[-1]
        self.assertEqual((a, p), (MOVE, 200))
        self.assertAlmostEqual(x, 0.2 + 0.1 / 2 ** 0.5 / 2.0, places=3)
        self.assertAlmostEqual(y, 0.7 - 0.1 / 2 ** 0.5, places=3)
        e.key_up("w")
        e.key_up("d")
        self.assertEqual(t[-1][0], UP)
        self.assertEqual(sum(1 for m in t if m[0] == DOWN), 1)

    def test_multitouch_uses_distinct_pointers(self):
        e, t, _ = make_engine([
            {"type": "tap", "key": "space", "x": 0.9, "y": 0.8},
            {"type": "joystick", "x": 0.2, "y": 0.7, "up": "w", "left": "a", "down": "s", "right": "d"},
        ])
        e.key_down("w")
        e.key_down("space")
        pids = {m[1] for m in t if m[0] == DOWN}
        self.assertEqual(len(pids), 2)

    def test_aim_recenters(self):
        e, t, _ = make_engine([{"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5,
                                "radius": 0.1, "sensitivity": 1.0}], aspect=1.0)
        e.mouse_motion(10, 0)  # ignored: aim off
        self.assertEqual(t, [])
        e.key_down("`")
        self.assertTrue(e.aim_active)
        e.mouse_motion(50, 0)
        self.assertEqual(t[0], (DOWN, AIM_POINTER_ID, 0.5, 0.5))
        self.assertEqual(t[-1], (MOVE, AIM_POINTER_ID, 0.55, 0.5))
        e.mouse_motion(80, 0)  # would exceed the radius -> lift and re-press at center
        self.assertEqual(t[-3][0], UP)
        self.assertEqual(t[-2], (DOWN, AIM_POINTER_ID, 0.5, 0.5))
        self.assertEqual(t[-1], (MOVE, AIM_POINTER_ID, 0.58, 0.5))
        e.key_down("`")
        self.assertFalse(e.aim_active)
        self.assertEqual(t[-1][0], UP)

    def test_swipe_animation(self):
        e, t, _ = make_engine([{"type": "swipe", "key": "e", "from": [0.5, 0.8],
                                "to": [0.5, 0.2], "duration": 100}])
        e.key_down("e")
        start = e._swipes[0]["start"]
        e.update(start + 0.05)
        self.assertEqual(t[-1], (MOVE, 300, 0.5, 0.5))
        e.update(start + 0.2)
        self.assertEqual(t[-1], (UP, 300, 0.5, 0.2))
        self.assertEqual(e._swipes, [])

    def test_android_action(self):
        e, _, k = make_engine([{"type": "android", "key": "escape", "action": "back"}])
        e.key_down("escape")
        self.assertEqual(k, [4])

    def test_release_all_lifts_every_finger(self):
        e, t, _ = make_engine([
            {"type": "tap", "key": "space", "x": 0.9, "y": 0.8},
            {"type": "joystick", "x": 0.2, "y": 0.7, "up": "w", "left": "a", "down": "s", "right": "d"},
            {"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5},
        ])
        e.key_down("space")
        e.key_down("w")
        e.key_down("`")
        e.mouse_motion(5, 5)
        e.release_all()
        downs = {m[1] for m in t if m[0] == DOWN}
        ups = {m[1] for m in t if m[0] == UP}
        self.assertEqual(downs, ups)
        self.assertFalse(e.aim_active)


class SkillTest(unittest.TestCase):
    SKILL = {"type": "skill", "key": "mouse_left", "x": 0.8, "y": 0.7, "radius": 0.1,
             "origin": [0.5, 0.5], "range": 0.4}

    def test_cursor_on_character_is_a_plain_tap(self):
        e, t, _ = make_engine([self.SKILL], aspect=2.0)
        e.mouse_position(0.5, 0.5)
        e.key_down("mouse_left")
        e.key_up("mouse_left")
        self.assertEqual(t, [(DOWN, 300, 0.8, 0.7), (UP, 300, 0.8, 0.7)])

    def test_drag_towards_cursor_and_fire_on_release(self):
        e, t, _ = make_engine([self.SKILL], aspect=2.0)
        e.mouse_position(0.6, 0.5)      # 0.2 frame heights right of the character
        e.key_down("mouse_left")
        # half of the range -> half of the radius, x offset divided by the aspect
        self.assertEqual(t[-1], (MOVE, 300, 0.825, 0.7))
        e.mouse_position(0.5, 0.0)      # far above: full radius, straight up
        self.assertEqual(t[-1], (MOVE, 300, 0.8, 0.6))
        e.key_up("mouse_left")
        self.assertEqual(t[-1], (UP, 300, 0.8, 0.6))
        e.mouse_position(0.9, 0.9)      # not held any more: nothing sent
        self.assertEqual(t[-1], (UP, 300, 0.8, 0.6))

    def test_release_all_lifts_held_skill(self):
        e, t, _ = make_engine([self.SKILL])
        e.mouse_position(0.9, 0.5)
        e.key_down("mouse_left")
        e.release_all()
        self.assertEqual(t[-1][0], UP)
        e.key_up("mouse_left")
        self.assertEqual(sum(1 for m in t if m[0] == UP), 1)


class ProfileTest(unittest.TestCase):
    def test_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Profile("Моя игра", [{"type": "tap", "key": "q", "x": 0.1, "y": 0.2}],
                        ["com.example"], os.path.join(d, "a.json"))
            p.save()
            with open(os.path.join(d, "bad.json"), "w") as f:
                f.write('{"mappings": [{"type": "nope"}]}')
            loaded = load_profiles(d)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].name, "Моя игра")
            self.assertEqual(loaded[0].packages, ["com.example"])
            self.assertEqual(loaded[0].keys_used(), ["q"])

    def test_bundled_profiles_are_valid(self):
        here = os.path.join(os.path.dirname(__file__), "..", "profiles")
        profiles = {p.name: p for p in load_profiles(here)}
        self.assertIn("Standoff 2", profiles)
        self.assertIn("Brawl Stars", profiles)
        self.assertEqual(profiles["Brawl Stars"].packages, ["com.supercell.brawlstars"])
        self.assertEqual(profiles["Standoff 2"].packages, ["com.axlebolt.standoff2"])


if __name__ == "__main__":
    unittest.main()

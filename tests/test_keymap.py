import os
import tempfile
import unittest

from phonecast import control
from phonecast.keymap import AIM_POINTER_ID, Engine, Profile, load_profiles

from phonecast.keymap import MIN_HOLD, TOUCH_STEP

DOWN, UP, MOVE = control.ACTION_DOWN, control.ACTION_UP, control.ACTION_MOVE
FRAME = 1 / 60  # games read touches once per frame


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Rig:
    """Engine with a fake clock; `run()` plays the app loop (update every 4 ms)."""

    def __init__(self, mappings, aspect=2.0):
        self.clock = Clock()
        self.sent = []      # (time, action, pointer, x, y)
        self.keycodes = []
        self.e = Engine(lambda a, p, x, y: self.sent.append((self.clock.t, a, p, round(x, 4), round(y, 4))),
                        self.keycodes.append, lambda: aspect, clock=self.clock)
        self.e.set_profile(Profile("t", mappings))

    def run(self, seconds=0.5):
        end = self.clock.t + seconds
        while self.clock.t < end:
            self.clock.t = round(self.clock.t + 0.004, 6)
            self.e.update()

    @property
    def touches(self):
        return [m[1:] for m in self.sent]

    def assert_like_a_finger(self, test):
        """No move in the same frame as the press, no release right after it."""
        down_at = {}
        for t, a, p, _x, _y in self.sent:
            if a == DOWN:
                down_at[p] = t
            elif a == MOVE:
                test.assertGreaterEqual(t - down_at[p], TOUCH_STEP - 1e-9)
                test.assertGreater(t - down_at[p], FRAME)
            elif a == UP:
                test.assertGreaterEqual(t - down_at[p], MIN_HOLD - 1e-9)


JOY = {"type": "joystick", "x": 0.2, "y": 0.7, "radius": 0.1,
       "up": "w", "left": "a", "down": "s", "right": "d"}


class EngineTest(unittest.TestCase):
    def test_tap_hold_and_release(self):
        r = Rig([{"type": "tap", "key": "space", "x": 0.9, "y": 0.8}])
        self.assertTrue(r.e.key_down("space"))
        self.assertTrue(r.e.key_down("space"))  # repeat does not press twice
        self.assertTrue(r.e.key_up("space"))    # released at once: still held MIN_HOLD
        self.assertEqual(r.touches, [(DOWN, 300, 0.9, 0.8)])
        r.run()
        self.assertEqual(r.touches, [(DOWN, 300, 0.9, 0.8), (UP, 300, 0.9, 0.8)])
        r.assert_like_a_finger(self)
        self.assertFalse(r.e.key_down("x"))

    def test_first_press_of_w_drags_the_joystick(self):
        # The bug: down + moves in one frame -> floating joystick did not move.
        r = Rig([JOY])
        r.e.key_down("w")
        self.assertEqual(r.touches, [(DOWN, 200, 0.2, 0.7)])  # only the press right now
        r.run(0.2)
        self.assertEqual(r.touches, [(DOWN, 200, 0.2, 0.7), (MOVE, 200, 0.2, 0.65),
                                     (MOVE, 200, 0.2, 0.6)])
        r.assert_like_a_finger(self)
        times = [m[0] for m in r.sent]
        self.assertGreater(times[2] - times[1], FRAME)  # half way and full are separate frames

    def test_joystick_directions_and_release(self):
        r = Rig([JOY])
        r.e.key_down("w")
        r.run(0.2)
        r.e.key_down("d")  # diagonal, x offset divided by the aspect ratio
        r.run(0.1)
        _t, a, p, x, y = r.sent[-1]
        self.assertEqual((a, p), (MOVE, 200))
        self.assertAlmostEqual(x, 0.2 + 0.1 / 2 ** 0.5 / 2.0, places=3)
        self.assertAlmostEqual(y, 0.7 - 0.1 / 2 ** 0.5, places=3)
        r.e.key_up("w")
        r.e.key_up("d")
        r.run(0.2)
        self.assertEqual(r.touches[-1][0], UP)
        self.assertEqual(sum(1 for m in r.touches if m[0] == DOWN), 1)
        r.assert_like_a_finger(self)

    def test_quick_w_then_d_both_move(self):
        # W pressed and released quickly, then D: each press must drag.
        r = Rig([JOY])
        r.e.key_down("w")
        r.run(0.03)
        r.e.key_up("w")
        r.e.key_down("d")
        r.run(0.3)
        moves = [m for m in r.touches if m[0] == MOVE]
        self.assertIn((MOVE, 200, 0.2, 0.6), moves)    # W reached full up
        self.assertIn((MOVE, 200, 0.25, 0.7), moves)   # D reached full right
        self.assertEqual(sum(1 for m in r.touches if m[0] == DOWN), 2)
        self.assertEqual(r.touches[-1][0], MOVE)       # D still held
        r.assert_like_a_finger(self)

    def test_multitouch_uses_distinct_pointers(self):
        r = Rig([{"type": "tap", "key": "space", "x": 0.9, "y": 0.8}, JOY])
        r.e.key_down("w")
        r.e.key_down("space")
        r.run()
        self.assertEqual(len({m[1] for m in r.touches if m[0] == DOWN}), 2)

    def test_aim_recenters(self):
        r = Rig([{"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5,
                  "radius": 0.1, "sensitivity": 1.0}], aspect=1.0)
        r.e.mouse_motion(10, 0)  # ignored: aim off
        self.assertEqual(r.touches, [])
        r.e.key_down("`")
        self.assertTrue(r.e.aim_active)
        r.e.mouse_motion(50, 0)
        r.run(0.1)
        self.assertEqual(r.touches, [(DOWN, AIM_POINTER_ID, 0.5, 0.5), (MOVE, AIM_POINTER_ID, 0.55, 0.5)])
        r.e.mouse_motion(80, 0)  # would exceed the radius -> lift, continue with another finger
        r.run(0.2)
        other = AIM_POINTER_ID + 1
        self.assertEqual(r.touches[-3:], [(UP, AIM_POINTER_ID, 0.55, 0.5), (DOWN, other, 0.5, 0.5),
                                         (MOVE, other, 0.58, 0.5)])
        r.e.key_down("`")
        self.assertFalse(r.e.aim_active)
        r.run(0.1)
        self.assertEqual(r.touches[-1][0], UP)
        r.assert_like_a_finger(self)

    def test_recentering_never_slides_a_finger_back(self):
        # The bug: same finger lifted and pressed again at the center within
        # one game frame looked like a slide back -> the camera jerked back.
        r = Rig([{"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5, "radius": 0.1}], aspect=1.0)
        r.e.key_down("`")
        for _ in range(40):          # keep turning right: many recenters
            r.e.mouse_motion(30, 0)
            r.run(0.01)
        r.run(0.2)
        last_x = {}
        for _t, a, p, x, _y in r.sent:
            if a == DOWN:
                last_x[p] = x
            elif a == MOVE:
                self.assertGreaterEqual(x, last_x[p])   # a finger only ever moves right
                last_x[p] = x
            elif a == UP:
                del last_x[p]
        self.assertGreater(sum(1 for m in r.touches if m[0] == DOWN), 3)
        r.assert_like_a_finger(self)

    def test_sensitivity_scale(self):
        r = Rig([{"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5, "radius": 0.4,
                  "sensitivity": 1.0}], aspect=1.0)
        r.e.sensitivity_scale = 0.5
        r.e.key_down("`")
        r.e.mouse_motion(100, 0)     # 100 counts * 1.0 * 0.5 / 1000
        r.run(0.1)
        self.assertEqual(r.touches[-1], (MOVE, AIM_POINTER_ID, 0.55, 0.5))

    def test_fast_mouse_motion_does_not_pile_up(self):
        r = Rig([{"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5, "radius": 0.4}], aspect=1.0)
        r.e.key_down("`")
        for _ in range(50):          # a 1000 Hz mouse between two frames
            r.e.mouse_motion(1, 0)
        r.run(0.1)
        self.assertEqual(r.touches, [(DOWN, AIM_POINTER_ID, 0.5, 0.5), (MOVE, AIM_POINTER_ID, 0.55, 0.5)])

    def test_swipe_animation(self):
        r = Rig([{"type": "swipe", "key": "e", "from": [0.5, 0.8], "to": [0.5, 0.2], "duration": 100}])
        r.e.key_down("e")
        r.run(0.3)
        self.assertEqual(r.touches[0], (DOWN, 300, 0.5, 0.8))
        self.assertEqual(r.touches[-1], (UP, 300, 0.5, 0.2))
        self.assertTrue(any(m[0] == MOVE and 0.2 < m[3] < 0.8 for m in r.touches))
        self.assertEqual(r.e._swipes, [])
        r.assert_like_a_finger(self)

    def test_android_action(self):
        r = Rig([{"type": "android", "key": "escape", "action": "back"}])
        r.e.key_down("escape")
        self.assertEqual(r.keycodes, [4])

    def test_release_all_lifts_every_finger(self):
        r = Rig([{"type": "tap", "key": "space", "x": 0.9, "y": 0.8}, JOY,
                 {"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5}])
        r.e.key_down("space")
        r.e.key_down("w")
        r.e.key_down("`")
        r.e.mouse_motion(5, 5)
        r.e.release_all()   # e.g. the window lost focus: nothing may stay pressed
        downs = {m[1] for m in r.touches if m[0] == DOWN}
        ups = {m[1] for m in r.touches if m[0] == UP}
        self.assertEqual(downs, ups)
        self.assertFalse(r.e.aim_active)
        r.run()
        self.assertEqual(downs, {m[1] for m in r.touches if m[0] == UP})


class SkillTest(unittest.TestCase):
    SKILL = {"type": "skill", "key": "mouse_left", "x": 0.8, "y": 0.7, "radius": 0.1,
             "origin": [0.5, 0.5], "range": 0.4}

    def test_cursor_on_character_is_a_plain_tap(self):
        r = Rig([self.SKILL], aspect=2.0)
        r.e.mouse_position(0.5, 0.5)
        r.e.key_down("mouse_left")
        r.e.key_up("mouse_left")
        r.run()
        self.assertEqual(r.touches, [(DOWN, 300, 0.8, 0.7), (UP, 300, 0.8, 0.7)])
        r.assert_like_a_finger(self)

    def test_drag_towards_cursor_and_fire_on_release(self):
        r = Rig([self.SKILL], aspect=2.0)
        r.e.mouse_position(0.6, 0.5)      # 0.2 frame heights right of the character
        r.e.key_down("mouse_left")
        self.assertEqual(r.touches, [(DOWN, 300, 0.8, 0.7)])
        r.run(0.2)
        # half way first, then half of the range -> half of the radius
        self.assertEqual(r.touches[1:], [(MOVE, 300, 0.8125, 0.7), (MOVE, 300, 0.825, 0.7)])
        r.e.mouse_position(0.5, 0.0)      # far above: full radius, straight up
        r.run(0.05)
        self.assertEqual(r.touches[-1], (MOVE, 300, 0.8, 0.6))
        r.e.key_up("mouse_left")
        r.run(0.1)
        self.assertEqual(r.touches[-1], (UP, 300, 0.8, 0.6))
        r.e.mouse_position(0.9, 0.9)      # not held any more: nothing sent
        r.run(0.1)
        self.assertEqual(r.touches[-1], (UP, 300, 0.8, 0.6))
        r.assert_like_a_finger(self)

    def test_quick_click_still_aims(self):
        # A fast click (down and up within one frame) must still drag before firing.
        r = Rig([self.SKILL], aspect=2.0)
        r.e.mouse_position(0.9, 0.5)
        r.e.key_down("mouse_left")
        r.e.key_up("mouse_left")
        r.run()
        self.assertEqual([m[0] for m in r.touches], [DOWN, MOVE, MOVE, UP])
        self.assertEqual(r.touches[-1][2:], r.touches[-2][2:])  # fired where it was aimed
        r.assert_like_a_finger(self)

    def test_release_all_lifts_held_skill(self):
        r = Rig([self.SKILL])
        r.e.mouse_position(0.9, 0.5)
        r.e.key_down("mouse_left")
        r.e.release_all()
        self.assertEqual(r.touches[-1][0], UP)
        r.e.key_up("mouse_left")
        r.run()
        self.assertEqual(sum(1 for m in r.touches if m[0] == UP), 1)


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

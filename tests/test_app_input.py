"""Mouse routing in game mode, without a window."""

import os
import tempfile
import time
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


def make_app(mappings, mode="control"):
    pygame.display.init()
    session = FakeSession()
    app = App(session, None, [Profile("p", mappings)], "/nonexistent", mode=mode)
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
        for _ in range(50):                          # the app loop keeps running
            time.sleep(0.005)
            app.engine.update()
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


class KeyEv:
    def __init__(self, type_, scancode):
        self.type, self.scancode, self.key, self.mod = type_, scancode, 0, 0


class WatchModeTest(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.TemporaryDirectory()
        os.environ["XDG_CONFIG_HOME"] = self.cfg.name

    def tearDown(self):
        del os.environ["XDG_CONFIG_HOME"]
        self.cfg.cleanup()

    def test_watch_mode_sends_nothing_to_the_phone(self):
        app, s = make_app([{"type": "tap", "key": "space", "x": 0.5, "y": 0.5}], mode="watch")
        app.keymap_on = False
        for ev in (pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(100, 100)),
                   pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(100, 100)),
                   pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(100, 100)),
                   pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1),
                   pygame.event.Event(pygame.TEXTINPUT, text="привет"),
                   pygame.event.Event(pygame.KEYDOWN, key=0, scancode=44, mod=0),   # space
                   pygame.event.Event(pygame.KEYDOWN, key=0, scancode=40, mod=0)):  # enter
            app.handle_event(ev)
        app._poll_foreground()
        self.assertEqual(s.sent, [])
        self.assertFalse(app.keymap_on)

    def test_switching_to_control_and_back(self):
        from phonecast import settings
        app, s = make_app([], mode="watch")
        app.keymap_on = False
        app.set_watch(False)
        self.assertEqual(settings.load()["mode"], "control")
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(100, 100)))
        self.assertEqual(touches(s), [(0, 0, 100, 100)])   # a click is a touch again
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(100, 100)))
        app.set_watch(True)
        self.assertEqual(settings.load()["mode"], "watch")
        n = len(s.sent)
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(100, 100)))
        self.assertEqual(len(s.sent), n)

    def test_switching_to_watch_releases_game_controls(self):
        app, s = make_app([{"type": "tap", "key": "space", "x": 0.5, "y": 0.5},
                           {"type": "aim", "toggle": "`", "x": 0.5, "y": 0.5, "auto": True}])
        app.keymap_on = False
        app.set_keymap(True)
        app.engine.key_down("space")
        app.set_watch(True)
        self.assertFalse(app.keymap_on)
        self.assertFalse(app.engine.aim_active)
        downs = {t[1] for t in touches(s) if t[0] == 0}
        ups = {t[1] for t in touches(s) if t[0] == 1}
        self.assertEqual(downs, ups)  # nothing stays pressed on the phone

    def test_waiting_screen_mode_buttons(self):
        from phonecast import settings
        from phonecast.launcher import Launcher
        pygame.display.init()
        screen = pygame.display.set_mode((760, 460))
        opts = settings.load()
        self.assertEqual(opts["mode"], "control")
        launcher = Launcher(opts, "/nonexistent")
        pygame.font.init()
        from phonecast.app import _font
        launcher.font, launcher.font_title, launcher.font_status = _font(16), _font(28), _font(19)
        launcher._draw(screen)
        rect = next(r for r, mode in launcher._mode_buttons if mode == "watch")
        pygame.event.clear()
        launcher.set_mode("watch")
        self.assertEqual(settings.load()["mode"], "watch")
        self.assertEqual(launcher.options["mode"], "watch")
        self.assertGreater(rect.w, 100)


class SeedProfilesTest(unittest.TestCase):
    def test_updated_bundled_profile_replaces_only_untouched_copies(self):
        with tempfile.TemporaryDirectory() as bundled, tempfile.TemporaryDirectory() as user:
            orig = cli.bundled_profiles_dir
            cli.bundled_profiles_dir = lambda: bundled
            try:
                for name in ("game.json", "other.json"):
                    open(os.path.join(bundled, name), "w").write('{"v": 1}')
                cli.seed_profiles(user)
                open(os.path.join(user, "other.json"), "w").write('{"moved": 1}')  # user edit
                for name in ("game.json", "other.json"):
                    open(os.path.join(bundled, name), "w").write('{"v": 2}')    # update
                cli.seed_profiles(user)
                self.assertEqual(open(os.path.join(user, "game.json")).read(), '{"v": 2}')
                self.assertEqual(open(os.path.join(user, "other.json")).read(), '{"moved": 1}')
                cli.seed_profiles(user)  # stable on the next start
                self.assertEqual(open(os.path.join(user, "other.json")).read(), '{"moved": 1}')
            finally:
                cli.bundled_profiles_dir = orig

    def test_higher_revision_replaces_even_an_edited_copy_and_keeps_a_backup(self):
        with tempfile.TemporaryDirectory() as bundled, tempfile.TemporaryDirectory() as user:
            orig = cli.bundled_profiles_dir
            cli.bundled_profiles_dir = lambda: bundled
            try:
                open(os.path.join(bundled, "g.json"), "w").write('{"v": 1}')
                cli.seed_profiles(user)
                open(os.path.join(user, "g.json"), "w").write('{"moved": 1}')        # edited v1
                open(os.path.join(bundled, "g.json"), "w").write('{"revision": 2, "v": 2}')
                cli.seed_profiles(user)
                self.assertEqual(open(os.path.join(user, "g.json")).read(), '{"revision": 2, "v": 2}')
                self.assertEqual(open(os.path.join(user, "g.json.bak")).read(), '{"moved": 1}')
                # the user edits revision 2 in the editor: it keeps its revision and stays
                open(os.path.join(user, "g.json"), "w").write('{"revision": 2, "moved": 2}')
                open(os.path.join(bundled, "g.json"), "w").write('{"revision": 2, "v": 3}')
                cli.seed_profiles(user)
                self.assertEqual(open(os.path.join(user, "g.json")).read(), '{"revision": 2, "moved": 2}')
            finally:
                cli.bundled_profiles_dir = orig

    def test_editor_save_keeps_revision(self):
        from phonecast.keymap import Profile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.json")
            open(path, "w").write('{"name": "x", "revision": 2, "mappings": []}')
            p = Profile.load(path)
            p.mappings.append({"type": "tap", "key": "q", "x": 0.1, "y": 0.1})
            p.save()
            self.assertEqual(Profile.load(path).revision, 2)

    def test_old_install_gets_fixed_standoff_profile(self):
        # Installed by the previous version: names-only record, v1 file unchanged.
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import subprocess
        try:
            v1 = subprocess.run(["git", "-C", repo, "show", "63f6171:profiles/standoff2.json"],
                                capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git history not available")
        with tempfile.TemporaryDirectory() as user:
            open(os.path.join(user, "standoff2.json"), "wb").write(v1)
            open(os.path.join(user, ".bundled"), "w").write("standoff2.json\n")
            cli.seed_profiles(user)
            data = open(os.path.join(user, "standoff2.json")).read()
            self.assertIn('"x": 0.776', data)  # the calibrated fire button

    def test_edited_v1_standoff_is_replaced_too(self):
        # The user moved circles of the broken v1 profile: revision 2 still wins.
        with tempfile.TemporaryDirectory() as user:
            open(os.path.join(user, "standoff2.json"), "w").write(
                '{"name": "Standoff 2", "mappings": [{"type": "tap", "key": "g", "x": 0.7, "y": 0.8}]}')
            open(os.path.join(user, ".bundled"), "w").write("standoff2.json\n")
            cli.seed_profiles(user)
            self.assertIn('"x": 0.776', open(os.path.join(user, "standoff2.json")).read())
            self.assertTrue(os.path.exists(os.path.join(user, "standoff2.json.bak")))


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

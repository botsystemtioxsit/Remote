import json
import os
import tempfile
import unittest

from phonecast import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        os.environ["XDG_CONFIG_HOME"] = self.dir.name

    def tearDown(self):
        del os.environ["XDG_CONFIG_HOME"]
        self.dir.cleanup()

    def test_load_creates_file_and_keeps_known_keys(self):
        self.assertEqual(settings.load(), settings.DEFAULTS)
        self.assertTrue(os.path.exists(settings.settings_path()))
        with open(settings.settings_path(), "w") as f:
            json.dump({"version": settings.VERSION, "max_fps": 30, "unknown": 1}, f)
        loaded = settings.load()
        self.assertEqual(loaded["max_fps"], 30)
        self.assertNotIn("unknown", loaded)

    def test_old_file_gets_new_quality_defaults(self):
        # Written by the previous version, which lowered quality on its own.
        os.makedirs(os.path.dirname(settings.settings_path()))
        with open(settings.settings_path(), "w") as f:
            json.dump({"max_size": 800, "max_fps": 30, "bit_rate": "8M", "fullscreen": True}, f)
        loaded = settings.load()
        self.assertEqual(loaded["quality"], "balanced")
        self.assertEqual(loaded["max_size"], settings.DEFAULTS["max_size"])
        self.assertEqual(loaded["max_fps"], 60)
        self.assertEqual(loaded["bit_rate"], settings.DEFAULTS["bit_rate"])
        self.assertTrue(loaded["fullscreen"])  # the user's own choices are kept
        with open(settings.settings_path()) as f:
            self.assertEqual(json.load(f)["version"], settings.VERSION)


class QualityTest(unittest.TestCase):
    def params(self, quality, screen):
        d = dict(settings.DEFAULTS)
        d["quality"] = quality
        return settings.video_params(d, screen)

    def test_presets(self):
        self.assertEqual(self.params("fast", 1920), (1024, "4M", 60))
        self.assertEqual(self.params("balanced", 1920), (1600, "10M", 60))
        self.assertEqual(self.params("balanced", 1366), (1366, "10M", 60))  # no more than the screen
        self.assertEqual(self.params("high", 1920), (1920, "16M", 60))      # the screen's own size
        self.assertEqual(self.params("high", 2560), (2560, "16M", 60))
        self.assertEqual(self.params("high", 1366), (1600, "16M", 60))

    def test_custom_uses_own_values(self):
        d = dict(settings.DEFAULTS, quality="custom", max_size=720, bit_rate="2M", max_fps=30)
        self.assertEqual(settings.video_params(d, 1920), (720, "2M", 30))

    def test_v2_file_moves_to_balanced(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["XDG_CONFIG_HOME"] = d
            try:
                os.makedirs(os.path.dirname(settings.settings_path()))
                with open(settings.settings_path(), "w") as f:
                    json.dump({"version": 2, "max_size": 1280, "bit_rate": "6M", "mode": "watch"}, f)
                loaded = settings.load()
                self.assertEqual(loaded["quality"], "balanced")
                self.assertEqual(loaded["mode"], "watch")
            finally:
                del os.environ["XDG_CONFIG_HOME"]


if __name__ == "__main__":
    unittest.main()

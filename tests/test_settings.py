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
        self.assertEqual(loaded["max_size"], 1280)
        self.assertEqual(loaded["max_fps"], 60)
        self.assertEqual(loaded["bit_rate"], "6M")
        self.assertTrue(loaded["fullscreen"])  # the user's own choices are kept
        with open(settings.settings_path()) as f:
            self.assertEqual(json.load(f)["version"], settings.VERSION)


if __name__ == "__main__":
    unittest.main()

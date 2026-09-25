import os
import tempfile
import unittest

from phonecast import settings


class SettingsTest(unittest.TestCase):
    def test_lower_quality_steps(self):
        s = dict(settings.DEFAULTS)
        self.assertEqual(s["max_size"], 1280)
        seen = []
        while True:
            what = settings.lower_quality(s)
            if not what:
                break
            seen.append((s["max_size"], s["max_fps"]))
        self.assertEqual(seen, [(1024, 60), (800, 60), (800, 30)])
        s["max_size"] = 0  # "phone resolution" -> first step
        settings.lower_quality(s)
        self.assertEqual(s["max_size"], 1920)

    def test_load_creates_file_and_keeps_known_keys(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["XDG_CONFIG_HOME"] = d
            try:
                self.assertEqual(settings.load(), settings.DEFAULTS)
                self.assertTrue(os.path.exists(settings.settings_path()))
                with open(settings.settings_path(), "w") as f:
                    f.write('{"max_fps": 30, "unknown": 1}')
                loaded = settings.load()
                self.assertEqual(loaded["max_fps"], 30)
                self.assertNotIn("unknown", loaded)
            finally:
                del os.environ["XDG_CONFIG_HOME"]


if __name__ == "__main__":
    unittest.main()

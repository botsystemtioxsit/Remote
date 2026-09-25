"""The application flow: waiting screen, connect, lost cable, reconnect, quit."""

import os
import stat
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


@unittest.skipUnless(sys.platform.startswith("linux"), "linux only")
class LauncherTest(unittest.TestCase):
    def test_wait_connect_reconnect_quit(self):
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
        os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
        server_file = os.path.join(tmp, "server.jar")
        open(server_file, "wb").close()
        for name, content in (("nodevice", ""), ("disconnect_after", "2"),
                              ("fg", "com.mojang.minecraftpe")):
            with open(os.path.join(tmp, name), "w") as f:
                f.write(content)

        import pygame
        from phonecast import settings
        from phonecast.launcher import Launcher

        options = settings.load()
        self.assertEqual(options["pc_mode_apps"], ["com.mojang.minecraftpe"])
        options["audio"] = False
        launcher = Launcher(options, os.path.join(tmp, "profiles"), server_file=server_file)
        seen = {"waiting": False, "lost_message": False}

        def script():
            time.sleep(1.5)
            seen["waiting"] = launcher.status == "Телефон не найден"
            os.remove(os.path.join(tmp, "nodevice"))       # the phone appears
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if "потеряна" in launcher.message:
                    seen["lost_message"] = True
                count = os.path.join(tmp, "sessions")
                if os.path.exists(count) and open(count).read() == "2" and seen["lost_message"]:
                    time.sleep(1.5)                          # second session running
                    break
                time.sleep(0.05)
            pygame.event.post(pygame.event.Event(pygame.QUIT))

        threading.Thread(target=script, daemon=True).start()
        self.assertEqual(launcher.run(), 0)

        self.assertTrue(seen["waiting"], "waiting screen was not shown without a phone")
        self.assertTrue(seen["lost_message"], "lost connection was not reported")
        self.assertEqual(open(os.path.join(tmp, "sessions")).read(), "2")
        with open(os.path.join(tmp, "control.bin"), "rb") as f:
            data = f.read()
        # Minecraft in the foreground: PC mode (virtual keyboard, id 1) switched on by itself
        self.assertIn(b"\x0c\x00\x01\x00\x00\x00\x00\x12Phonecast Keyboard", data)


if __name__ == "__main__":
    unittest.main()

"""Thin wrapper around the `adb` command line tool."""

import re
import shutil
import subprocess


class AdbError(RuntimeError):
    pass


def adb_path():
    path = shutil.which("adb")
    if not path:
        raise AdbError(
            "adb not found. Install it, e.g.:\n"
            "  Debian/Ubuntu: sudo apt install adb\n"
            "  Fedora:        sudo dnf install android-tools\n"
            "  Arch:          sudo pacman -S android-tools")
    return path


class Adb:
    def __init__(self, serial=None):
        self.adb = adb_path()
        self.serial = serial

    def _cmd(self, *args):
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd + list(args)

    def run(self, *args, check=True, timeout=30):
        proc = subprocess.run(self._cmd(*args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=timeout)
        if check and proc.returncode != 0:
            raise AdbError("adb %s failed: %s" % (" ".join(args), (proc.stderr or proc.stdout).strip()))
        return proc.stdout

    def popen(self, *args, **kwargs):
        return subprocess.Popen(self._cmd(*args), **kwargs)

    def devices(self):
        """Returns [(serial, state, description)]."""
        out = subprocess.run([self.adb, "devices", "-l"], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, timeout=15).stdout
        result = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                state = parts[1]
                if line.split(None, 1)[1].startswith("no permissions"):
                    state = "no permissions"
                desc = " ".join(p for p in parts[2:] if p.startswith(("model:", "device:")))
                result.append((parts[0], state, desc))
        return result

    def restart_server_as_root(self):
        """Restart the adb server with root rights if sudo needs no password.

        Needed when the user may not open USB devices (common in the Linux
        container of Chromebooks, where udev rules do not apply). Clients,
        including this program, keep running as the normal user.
        Returns True if the restart was done.
        """
        if not shutil.which("sudo"):
            return False
        try:
            if subprocess.run(["sudo", "-n", "true"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=5).returncode != 0:
                return False
            subprocess.run([self.adb, "kill-server"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
            subprocess.run(["sudo", "-n", self.adb, "start-server"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return True

    def select_device(self, pick_first=False):
        """Pick the device to use, preferring USB-connected ones."""
        if self.serial:
            return self.serial
        devices = self.devices()
        ready = [d for d in devices if d[1] == "device"]
        if not ready:
            unauthorized = [d for d in devices if d[1] == "unauthorized"]
            if unauthorized:
                raise AdbError(
                    "The phone is connected but not authorized.\n"
                    "Unlock it and accept the 'Allow USB debugging?' dialog.")
            raise AdbError(
                "No device found. Check that:\n"
                "  1. the cable supports data (not only charging);\n"
                "  2. Developer options -> USB debugging is enabled on the phone;\n"
                "  3. `adb devices` lists the phone.")
        usb = [d for d in ready if ":" not in d[0]]  # tcpip devices look like ip:port
        candidates = usb or ready
        if len(candidates) > 1 and not pick_first:
            names = "\n".join("  %s  %s" % (d[0], d[2]) for d in candidates)
            raise AdbError("Several devices connected, pick one with -s SERIAL:\n" + names)
        self.serial = candidates[0][0]
        return self.serial

    def push(self, local, remote):
        self.run("push", local, remote, timeout=60)

    def forward(self, local_port, remote):
        self.run("forward", "tcp:%d" % local_port, remote)

    def forward_remove(self, local_port):
        self.run("forward", "--remove", "tcp:%d" % local_port, check=False)

    def shell(self, command, timeout=15):
        return self.run("shell", command, check=False, timeout=timeout)

    def foreground_package(self):
        """Package name of the app currently in focus, or None."""
        out = self.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", timeout=5)
        for line in out.splitlines():
            m = re.search(r"\s(\S+)/\S+\}", line)
            if m and "." in m.group(1):
                return m.group(1)
        return None

    def sdk_version(self):
        try:
            return int(self.shell("getprop ro.build.version.sdk").strip())
        except ValueError:
            return None

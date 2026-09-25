"""phonecast — mirror and control an Android phone over USB, with key mapping for games."""

import argparse
import hashlib
import os
import shutil
import sys

from . import settings as settings_mod
from .adb import Adb, AdbError


def bundled_profiles_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles")


# sha256 of bundled profiles shipped by earlier versions without a recorded
# hash: a user file identical to one of them was never edited, so it may be
# replaced by the new version.
PREVIOUS_BUNDLED_SHA256 = {
    "98c1c13cf3f9906e8d0574cb4099d820cfa1ad2ca55b0dff31b1213f6395a2f6",  # standoff2.json v1
    "e6a21124e1159b950dbd09b94c5a3a916d3ec8deb98bbd7bfdd2dcead9f00822",  # brawlstars.json v1
}


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def seed_profiles(directory):
    """Bring the profiles shipped with the program into the user's folder.

    - a new bundled profile is copied once;
    - an updated bundled profile replaces the user's copy only if the user
      never changed that copy;
    - profiles the user deleted stay deleted, edited ones are never touched.
    The record (.bundled) holds "file sha256" of what was delivered.
    """
    os.makedirs(directory, exist_ok=True)
    src = bundled_profiles_dir()
    if not os.path.isdir(src):
        return
    record_path = os.path.join(directory, ".bundled")
    record = {}
    try:
        with open(record_path, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if parts:
                    record[parts[0]] = parts[1] if len(parts) > 1 else None
    except FileNotFoundError:
        # Earlier versions copied the examples without a record.
        record = {f: None for f in os.listdir(directory) if f.endswith(".json")}
    for fname in sorted(os.listdir(src)):
        if not fname.endswith(".json"):
            continue
        bundled = os.path.join(src, fname)
        new_sha = _sha256(bundled)
        dest = os.path.join(directory, fname)
        if fname not in record:
            if not os.path.exists(dest):
                shutil.copy(bundled, dest)
            record[fname] = new_sha
        elif record[fname] != new_sha and os.path.exists(dest):
            delivered = record[fname]
            user_sha = _sha256(dest)
            if user_sha == delivered or (delivered is None and user_sha in PREVIOUS_BUNDLED_SHA256):
                shutil.copy(bundled, dest)  # untouched copy: take the new version
                record[fname] = new_sha
    with open(record_path, "w", encoding="utf-8") as f:
        for fname in sorted(record):
            f.write(("%s %s\n" % (fname, record[fname])) if record[fname] else fname + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="phonecast",
        description="Трансляция экрана Android-телефона по USB с управлением и раскладкой для игр. "
                    "Настройки по умолчанию хранятся в " + settings_mod.settings_path())
    p.add_argument("-s", "--serial", help="серийный номер устройства (если подключено несколько)")
    p.add_argument("-m", "--max-size", type=int,
                   help="макс. размер большей стороны видео, px (0 = как на телефоне)")
    p.add_argument("-b", "--bit-rate", help="битрейт видео, напр. 8M, 16M")
    p.add_argument("--max-fps", type=int, help="ограничение FPS")
    p.add_argument("--no-audio", action="store_true", help="не передавать звук")
    p.add_argument("-p", "--profile", help="профиль раскладки при запуске (имя или файл)")
    p.add_argument("-f", "--fullscreen", action="store_true", help="запустить в полноэкранном режиме")
    p.add_argument("--screen-off", action="store_true",
                   help="выключить экран телефона во время трансляции (экономит батарею)")
    p.add_argument("--no-stay-awake", action="store_true",
                   help="не держать телефон включённым, пока он подключён")
    p.add_argument("--profiles-dir", default=os.path.join(settings_mod.config_dir(), "profiles"),
                   help="папка с профилями раскладок")
    p.add_argument("--server-file", help="путь к scrcpy-server (если нет интернета для скачивания)")
    p.add_argument("--list-devices", action="store_true", help="показать подключённые устройства")
    p.add_argument("-v", "--verbose", action="store_true", help="подробный лог с телефона")
    args = p.parse_args(argv)

    if args.list_devices:
        try:
            for serial, state, desc in Adb().devices():
                print("%-24s %-14s %s" % (serial, state, desc))
        except AdbError as e:
            print("phonecast: %s" % e, file=sys.stderr)
            return 1
        return 0

    options = settings_mod.load()
    if args.max_size is not None:
        options["max_size"] = args.max_size
    if args.bit_rate:
        options["bit_rate"] = args.bit_rate
    if args.max_fps:
        options["max_fps"] = args.max_fps
    if args.no_audio:
        options["audio"] = False
    if args.fullscreen:
        options["fullscreen"] = True
    if args.screen_off:
        options["screen_off"] = True

    seed_profiles(args.profiles_dir)

    # Imported late so that --help and --list-devices work without a display.
    from .launcher import Launcher

    launcher = Launcher(options, args.profiles_dir, serial=args.serial,
                        start_profile=args.profile, server_file=args.server_file,
                        verbose=args.verbose, stay_awake=not args.no_stay_awake)
    try:
        return launcher.run()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())

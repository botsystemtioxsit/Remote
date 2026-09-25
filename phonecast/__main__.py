"""phonecast — mirror and control an Android phone over USB, with key mapping for games."""

import argparse
import os
import shutil
import sys

from . import settings as settings_mod
from .adb import Adb, AdbError


def bundled_profiles_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles")


def seed_profiles(directory):
    """On first run, copy the example profiles shipped with the program."""
    if os.path.isdir(directory):
        return
    os.makedirs(directory)
    src = bundled_profiles_dir()
    if os.path.isdir(src):
        for fname in os.listdir(src):
            if fname.endswith(".json"):
                shutil.copy(os.path.join(src, fname), os.path.join(directory, fname))


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

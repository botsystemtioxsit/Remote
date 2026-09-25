"""phonecast — mirror and control an Android phone over USB, with key mapping for games."""

import argparse
import os
import shutil
import sys

from .adb import Adb, AdbError
from .keymap import load_profiles
from .session import Session, SessionError


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "phonecast")


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


def parse_bit_rate(text):
    text = text.strip().upper()
    mult = 1
    if text.endswith("M"):
        mult, text = 1_000_000, text[:-1]
    elif text.endswith("K"):
        mult, text = 1_000, text[:-1]
    return int(float(text) * mult)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="phonecast",
        description="Трансляция экрана Android-телефона по USB с управлением и раскладкой для игр.")
    p.add_argument("-s", "--serial", help="серийный номер устройства (если подключено несколько)")
    p.add_argument("-m", "--max-size", type=int, default=1600,
                   help="макс. размер большей стороны видео, px (по умолчанию 1600; 0 = как на телефоне)")
    p.add_argument("-b", "--bit-rate", default="8M", help="битрейт видео, напр. 8M, 16M (по умолчанию 8M)")
    p.add_argument("--max-fps", type=int, default=60, help="ограничение FPS (по умолчанию 60)")
    p.add_argument("--no-audio", action="store_true", help="не передавать звук")
    p.add_argument("-p", "--profile", help="профиль раскладки при запуске (имя или файл)")
    p.add_argument("-f", "--fullscreen", action="store_true", help="запустить в полноэкранном режиме")
    p.add_argument("--screen-off", action="store_true",
                   help="выключить экран телефона во время трансляции (экономит батарею)")
    p.add_argument("--no-stay-awake", action="store_true",
                   help="не держать телефон включённым, пока он подключён")
    p.add_argument("--profiles-dir", default=os.path.join(config_dir(), "profiles"),
                   help="папка с профилями раскладок")
    p.add_argument("--server-file", help="путь к scrcpy-server (если нет интернета для скачивания)")
    p.add_argument("--list-devices", action="store_true", help="показать подключённые устройства")
    p.add_argument("-v", "--verbose", action="store_true", help="подробный лог с телефона")
    args = p.parse_args(argv)

    try:
        adb = Adb(args.serial)
        if args.list_devices:
            for serial, state, desc in adb.devices():
                print("%-24s %-14s %s" % (serial, state, desc))
            return 0
        adb.select_device()
    except AdbError as e:
        print("phonecast: %s" % e, file=sys.stderr)
        return 1

    seed_profiles(args.profiles_dir)
    profiles = load_profiles(args.profiles_dir)

    session = Session(adb, max_size=args.max_size, bit_rate=parse_bit_rate(args.bit_rate),
                      max_fps=args.max_fps, audio=not args.no_audio, server_file=args.server_file,
                      stay_awake=not args.no_stay_awake, verbose=args.verbose)
    try:
        session.start()
    except (SessionError, AdbError, OSError) as e:
        session.close()
        print("phonecast: %s" % e, file=sys.stderr)
        return 1

    # Imported late so that --help and device errors work without a display.
    from .app import App

    app = App(session, adb, profiles, args.profiles_dir, start_profile=args.profile,
              fullscreen=args.fullscreen, audio=not args.no_audio, screen_off=args.screen_off)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        session.close()
    if app.device_gone:
        print("phonecast: соединение с телефоном потеряно", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

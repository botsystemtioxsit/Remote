"""User settings stored in ~/.config/phonecast/settings.json."""

import json
import os

# Bumped when defaults change in a way that must replace values saved by an
# older version (quality settings that older versions lowered automatically).
VERSION = 2
QUALITY_KEYS = ("max_size", "bit_rate", "max_fps")

DEFAULTS = {
    "version": VERSION,
    "max_size": 1280,        # larger side of the video, px (0 = phone resolution)
    "bit_rate": "6M",
    "max_fps": 60,
    "audio": True,
    "fullscreen": False,
    "screen_off": False,     # turn the phone screen off while mirroring
    # "control": mouse/keyboard/game controls; "watch": picture and sound only
    "mode": "control",
    # Apps in which PC mode (real keyboard + mouse on the phone) turns on by itself
    "pc_mode_apps": ["com.mojang.minecraftpe"],
}


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "phonecast")


def settings_path():
    return os.path.join(config_dir(), "settings.json")


def load():
    settings = dict(DEFAULTS)
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version", 1) < VERSION:
            for key in QUALITY_KEYS + ("version",):
                data.pop(key, None)
            settings.update({k: v for k, v in data.items() if k in DEFAULTS})
            save(settings)
        else:
            settings.update({k: v for k, v in data.items() if k in DEFAULTS})
    except FileNotFoundError:
        save(settings)  # create it so it is easy to find and edit
    except (OSError, ValueError) as e:
        print("phonecast: ignoring broken %s: %s" % (settings_path(), e))
    return settings


def save(settings):
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as e:
        print("phonecast: cannot save settings: %s" % e)

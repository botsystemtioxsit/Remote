"""User settings stored in ~/.config/phonecast/settings.json."""

import json
import os

# Bumped when defaults change in a way that must replace values saved by an
# older version (quality settings that older versions lowered automatically).
VERSION = 3
QUALITY_KEYS = ("max_size", "bit_rate", "max_fps")

# Quality presets: (larger side of the video in px, bit rate, fps).
# "screen" = as many pixels as the computer screen has (never more than the phone).
PRESETS = {
    "fast": (1024, "4M", 60),
    "balanced": (1600, "10M", 60),
    "high": ("screen", "16M", 60),
}
PRESET_NAMES = {"fast": "Быстрое", "balanced": "Баланс", "high": "Высокое", "custom": "Своё"}
PRESET_ORDER = ["fast", "balanced", "high"]

DEFAULTS = {
    "version": VERSION,
    # fast / balanced / high, or "custom" to use max_size, bit_rate and max_fps below
    "quality": "balanced",
    "max_size": 1600,        # larger side of the video, px (0 = phone resolution)
    "bit_rate": "10M",
    "max_fps": 60,
    "audio": True,
    "fullscreen": False,
    "screen_off": False,     # turn the phone screen off while mirroring
    # "control": mouse/keyboard/game controls; "watch": picture and sound only
    "mode": "control",
    # draw the key labels of the game controls over the game (F4)
    "show_hints": False,
    # mouse sensitivity in games: camera look (times the profile's own) and PC mode
    "mouse_sensitivity": 0.6,
    # colour theme of the window, see phonecast/theme.py
    "theme": "graphite",
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
            # Quality values of older versions were low defaults, not choices.
            for key in QUALITY_KEYS + ("version", "quality"):
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


def video_params(settings, screen_long_side):
    """(max_size, bit_rate, max_fps) for the chosen quality."""
    preset = PRESETS.get(settings.get("quality"))
    if preset is None:  # "custom"
        return settings["max_size"], settings["bit_rate"], settings["max_fps"]
    size, bit_rate, fps = preset
    if size == "screen":
        size = max(1600, int(screen_long_side or 1920))
    else:
        size = min(size, max(1024, int(screen_long_side or size)))
    return size, bit_rate, fps

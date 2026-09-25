"""User settings stored in ~/.config/phonecast/settings.json."""

import json
import os

DEFAULTS = {
    "max_size": 1280,        # larger side of the video, px (0 = phone resolution)
    "bit_rate": "8M",
    "max_fps": 60,
    "audio": True,
    "fullscreen": False,
    "screen_off": False,     # turn the phone screen off while mirroring
    # Apps in which PC mode (real keyboard + mouse on the phone) turns on by itself
    "pc_mode_apps": ["com.mojang.minecraftpe"],
}

# Steps used when the computer cannot keep up with the video.
QUALITY_STEPS = [1920, 1600, 1280, 1024, 800]


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


def lower_quality(settings):
    """Make the video lighter. Returns a description, or None if already minimal."""
    size = settings["max_size"] or 10000
    for step in QUALITY_STEPS:
        if step < size:
            settings["max_size"] = step
            return "разрешение снижено до %d px" % step
    if settings["max_fps"] > 30:
        settings["max_fps"] = 30
        return "частота кадров снижена до 30"
    return None

"""Key mapping profiles and the engine that turns key presses into touches.

Coordinates in profiles are normalized to the video frame: (0, 0) is the
top-left corner of the phone screen, (1, 1) the bottom-right corner. Radii are
fractions of the frame *height*, so circles stay round in any aspect ratio.

Mapping types:

  tap       {"type": "tap", "key": "space", "x": 0.9, "y": 0.8}
            Finger down while the key is held, up on release.

  joystick  {"type": "joystick", "x": 0.15, "y": 0.72, "radius": 0.12,
             "up": "w", "left": "a", "down": "s", "right": "d"}
            Virtual stick: a finger is dragged from the center towards the
            pressed directions. Optional "walk": "lshift" holds the stick at
            half deflection while pressed.

  aim       {"type": "aim", "toggle": "`", "x": 0.65, "y": 0.45,
             "radius": 0.3, "sensitivity": 1.0, "auto": true}
            Mouse look. The toggle key captures the mouse; mouse motion then
            drags a finger around (x, y), re-centering when it goes too far.
            "auto": capture the mouse as soon as the key mapping is enabled.

  skill     {"type": "skill", "key": "mouse_left", "x": 0.84, "y": 0.74,
             "radius": 0.1, "origin": [0.5, 0.5], "range": 0.35}
            Aimed ability (Brawl Stars attack/super, MOBA skills): while the
            key is held, a finger is dragged from (x, y) towards the mouse
            cursor as seen from "origin" (where the character is on screen);
            releasing the key fires. With the cursor on the character it is a
            plain tap (auto-aim). A cursor "range" away from the origin gives
            the full "radius" deflection.

  swipe     {"type": "swipe", "key": "e", "from": [0.5, 0.8], "to": [0.5, 0.3],
             "duration": 150}

  android   {"type": "android", "key": "escape", "action": "back"}
            Sends a system key: back, home, recents, menu, power,
            volume_up, volume_down, mute.

Any "key" may also be a mouse button: mouse_left, mouse_right, mouse_middle,
mouse_x1, mouse_x2.
"""

import copy
import json
import math
import os
import re
import time

from . import control
from .keys import ANDROID_ACTIONS

AIM_POINTER_ID = 100
SKILL_DEADZONE = 0.03

# Touch timing. Games read touches once per frame (~16 ms at 60 fps): a
# finger that goes down and moves within the same frame is seen as appearing
# at its final position, so a floating joystick centers itself under it and
# nothing moves. Space events like a real finger does.
TOUCH_STEP = 0.025      # a move comes at least this long after the finger went down
MIN_HOLD = 0.04         # a finger is not lifted sooner than this after going down
REPRESS_GAP = 0.02      # a lifted finger goes down again only after this
JOYSTICK_POINTER_BASE = 200
MAPPING_POINTER_BASE = 300


class Profile:
    def __init__(self, name, mappings=None, packages=None, path=None, revision=None):
        self.name = name
        self.mappings = mappings or []
        self.packages = packages or []
        self.path = path
        self.revision = revision  # version of a profile shipped with the program

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data, path)

    @classmethod
    def from_dict(cls, data, path=None):
        mappings = data.get("mappings", [])
        for m in mappings:
            validate_mapping(m)
        return cls(data.get("name") or os.path.splitext(os.path.basename(path or "profile"))[0],
                   mappings, data.get("packages", []), path, data.get("revision"))

    def to_dict(self):
        data = {"name": self.name, "packages": self.packages, "mappings": self.mappings}
        if self.revision is not None:
            data = {"name": self.name, "revision": self.revision, "packages": self.packages,
                    "mappings": self.mappings}
        return data

    def save(self, path=None):
        path = path or self.path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
        self.path = path

    def keys_used(self):
        used = []
        for m in self.mappings:
            used.extend(mapping_keys(m))
        return used


def mapping_keys(m):
    t = m["type"]
    if t == "joystick":
        return [m[k] for k in ("up", "left", "down", "right", "walk") if m.get(k)]
    if t == "aim":
        return [m["toggle"]]
    return [m["key"]]


def validate_mapping(m):
    t = m.get("type")
    required = {
        "tap": ("key", "x", "y"),
        "joystick": ("x", "y", "up", "left", "down", "right"),
        "aim": ("toggle", "x", "y"),
        "swipe": ("key", "from", "to"),
        "skill": ("key", "x", "y"),
        "android": ("key", "action"),
    }
    if t not in required:
        raise ValueError("unknown mapping type: %r" % (t,))
    for k in required[t]:
        if k not in m:
            raise ValueError("mapping %r is missing %r" % (t, k))
    if t == "android" and m["action"] not in ANDROID_ACTIONS:
        raise ValueError("unknown android action %r (known: %s)"
                         % (m["action"], ", ".join(sorted(ANDROID_ACTIONS))))


def slugify(name):
    slug = re.sub(r"[^\w-]+", "_", name.strip().lower(), flags=re.UNICODE).strip("_")
    return slug or "profile"


def load_profiles(directory):
    profiles = []
    if os.path.isdir(directory):
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(directory, fname)
            try:
                profiles.append(Profile.load(path))
            except (OSError, ValueError) as e:
                print("phonecast: skipping profile %s: %s" % (path, e))
    return profiles


def _clamp01(v):
    return min(max(v, 0.0), 1.0)


class Engine:
    """Turns key/mouse events into touch events according to a profile.

    `touch(action, pointer_id, nx, ny)` sends a touch with normalized coords,
    `keycode(keycode)` sends a full press+release of an Android key and
    `aspect()` returns the current frame width / height.
    """

    def __init__(self, touch, keycode, aspect, clock=time.monotonic):
        self._raw = touch
        self._clock = clock
        self._queue = {}       # pointer id -> [[due, action, x, y], ...] not sent yet
        self._down_at = {}     # pointer id -> time its last DOWN is (or will be) sent
        self._up_at = {}       # pointer id -> time its last UP is (or will be) sent
        self._keycode = keycode
        self._aspect = aspect
        self.profile = None
        self._by_key = {}
        self._held = {}        # key name -> (pointer id, x, y) of the finger held by that key
        self._joy_state = {}   # joystick index -> dict
        self._swipes = []      # active swipe animations
        self._skills = {}      # key name -> [pointer id, mapping, current finger pos]
        self.mouse_pos = (0.5, 0.5)  # cursor position, normalized to the frame
        self.aim = None        # aim mapping of the profile, if any
        self.sensitivity_scale = 1.0  # user's mouse sensitivity (settings), times the profile's
        self._aim_pid = AIM_POINTER_ID
        self.aim_active = False
        self._aim_pos = None   # current finger position while aiming, None if up

    # ----- profile -------------------------------------------------------

    def set_profile(self, profile):
        self.release_all()
        self.profile = profile
        self.reload()

    def reload(self):
        """Rebuild lookup tables after the profile's mappings changed."""
        self.release_all()
        self._by_key = {}
        self.aim = None
        self._joy_state = {}
        if not self.profile:
            return
        for i, m in enumerate(self.profile.mappings):
            t = m["type"]
            if t == "joystick":
                self._joy_state[i] = {"pressed": set(), "down": None, "walk": False}
                for d in ("up", "left", "down", "right", "walk"):
                    if m.get(d):
                        self._by_key.setdefault(m[d], []).append((i, m, d))
            elif t == "aim":
                self.aim = m
                self._by_key.setdefault(m["toggle"], []).append((i, m, "toggle"))
            else:
                self._by_key.setdefault(m["key"], []).append((i, m, None))

    def handles(self, key):
        return key in self._by_key

    def mapping_type(self, key):
        entries = self._by_key.get(key)
        return entries[0][1]["type"] if entries else None

    # ----- events --------------------------------------------------------

    def key_down(self, key):
        """Returns True if the key is mapped (and therefore consumed)."""
        entries = self._by_key.get(key)
        if not entries:
            return False
        for i, m, role in entries:
            t = m["type"]
            if t == "tap":
                if key not in self._held:
                    pid = MAPPING_POINTER_BASE + i
                    self._held[key] = (pid, m["x"], m["y"])
                    self._touch(control.ACTION_DOWN, pid, m["x"], m["y"])
            elif t == "joystick":
                st = self._joy_state[i]
                if role == "walk":
                    st["walk"] = True
                else:
                    st["pressed"].add(role)
                self._update_joystick(i, m)
            elif t == "aim":
                self.set_aim_active(not self.aim_active)
            elif t == "swipe":
                self._start_swipe(i, m)
            elif t == "android":
                self._keycode(ANDROID_ACTIONS[m["action"]])
            elif t == "skill":
                if key not in self._skills:
                    pid = MAPPING_POINTER_BASE + i
                    self._skills[key] = [pid, m, (m["x"], m["y"])]
                    self._touch(control.ACTION_DOWN, pid, m["x"], m["y"])
                    self._move_skill(key, first=True)
        return True

    def key_up(self, key):
        entries = self._by_key.get(key)
        if not entries:
            return False
        for i, m, role in entries:
            t = m["type"]
            if t == "tap":
                held = self._held.pop(key, None)
                if held is not None:
                    self._touch(control.ACTION_UP, *held)
            elif t == "joystick":
                st = self._joy_state[i]
                if role == "walk":
                    st["walk"] = False
                else:
                    st["pressed"].discard(role)
                self._update_joystick(i, m)
            elif t == "skill" and key in self._skills:
                self._move_skill(key)
                pid, _m, pos = self._skills.pop(key)
                self._touch(control.ACTION_UP, pid, *pos)
        return True

    def mouse_position(self, nx, ny):
        """Absolute cursor position (normalized) while the mouse is free."""
        self.mouse_pos = (nx, ny)
        for key in self._skills:
            self._move_skill(key)

    def _move_skill(self, key, first=False):
        st = self._skills[key]
        pid, m, pos = st
        aspect = self._aspect() or 1.0
        ox, oy = m.get("origin", (0.5, 0.5))
        dx = (self.mouse_pos[0] - ox) * aspect   # in frame-height units
        dy = self.mouse_pos[1] - oy
        dist = math.hypot(dx, dy)
        if dist < SKILL_DEADZONE:
            target = (m["x"], m["y"])
        else:
            k = min(1.0, dist / float(m.get("range", 0.35))) * float(m.get("radius", 0.1))
            target = (_clamp01(m["x"] + dx / dist * k / aspect), _clamp01(m["y"] + dy / dist * k))
        if target != pos:
            st[2] = target
            if first:
                # like the joystick: half way first, then the full drag
                self._touch(control.ACTION_MOVE, pid, (pos[0] + target[0]) / 2,
                            (pos[1] + target[1]) / 2, coalesce=False)
                self._touch(control.ACTION_MOVE, pid, *target, gap=TOUCH_STEP, coalesce=False)
            else:
                self._touch(control.ACTION_MOVE, pid, *target)

    def mouse_motion(self, dx, dy):
        """Relative mouse motion (in window pixels) while aiming."""
        if not (self.aim_active and self.aim):
            return
        m = self.aim
        aspect = self._aspect() or 1.0
        sens = float(m.get("sensitivity", 1.0)) * self.sensitivity_scale
        radius = float(m.get("radius", 0.3))
        cx, cy = m["x"], m["y"]
        if self._aim_pos is None:
            self._aim_pos = (cx, cy)
            self._touch(control.ACTION_DOWN, self._aim_pid, cx, cy)
        # sensitivity 1.0: 1000 mouse counts move the finger by one frame height
        nx = self._aim_pos[0] + dx * sens / 1000.0 / aspect
        ny = self._aim_pos[1] + dy * sens / 1000.0
        dist = math.hypot((nx - cx) * aspect, ny - cy)
        if dist > radius or not (0.01 < nx < 0.99 and 0.01 < ny < 0.99):
            # Lift the finger and continue turning with *another* finger from
            # the center. With the same finger, a game running slower than the
            # lift/press gap would see it slide back to the center, turning
            # the camera back ("jerks back and forth").
            self._touch(control.ACTION_UP, self._aim_pid, *self._aim_pos)
            self._aim_pid = AIM_POINTER_ID + 1 if self._aim_pid == AIM_POINTER_ID else AIM_POINTER_ID
            self._touch(control.ACTION_DOWN, self._aim_pid, cx, cy)
            nx = cx + dx * sens / 1000.0 / aspect
            ny = cy + dy * sens / 1000.0
        nx, ny = _clamp01(nx), _clamp01(ny)
        self._aim_pos = (nx, ny)
        self._touch(control.ACTION_MOVE, self._aim_pid, nx, ny)

    def set_aim_active(self, active):
        if not self.aim:
            active = False
        if not active and self._aim_pos is not None:
            self._touch(control.ACTION_UP, self._aim_pid, *self._aim_pos)
            self._aim_pos = None
        self.aim_active = active

    def update(self, now=None):
        """Send touches whose time has come and advance swipes. Call every frame."""
        now = self._clock() if now is None else now
        for pid, q in self._queue.items():
            while q and q[0][0] <= now:
                due, action, x, y = q.pop(0)
                self._raw(action, pid, x, y)
                late = now - due
                if late > 0:
                    # keep the spacing of what follows (this loop runs every few ms)
                    for item in q:
                        item[0] += late
                    if action == control.ACTION_DOWN:
                        self._down_at[pid] = now
                    elif action == control.ACTION_UP:
                        self._up_at[pid] = now
        if not self._swipes:
            return
        still = []
        for s in self._swipes:
            t = (now - s["start"]) / s["duration"] if s["duration"] > 0 else 1.0
            x0, y0 = s["from"]
            x1, y1 = s["to"]
            if t >= 1.0:
                self._touch(control.ACTION_MOVE, s["pid"], x1, y1)
                self._touch(control.ACTION_UP, s["pid"], x1, y1)
            else:
                self._touch(control.ACTION_MOVE, s["pid"], x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
                still.append(s)
        self._swipes = still

    def release_all(self):
        """Lift every finger the engine holds (profile switch, focus loss...)."""
        for pid, q in self._queue.items():
            for _due, action, x, y in q:
                self._raw(action, pid, x, y)
        self._queue = {}
        for held in self._held.values():
            self._raw(control.ACTION_UP, *held)
        for i, st in self._joy_state.items():
            st["pressed"].clear()
            st["walk"] = False
            if st["down"]:
                self._raw(control.ACTION_UP, JOYSTICK_POINTER_BASE + i, *st["down"])
                st["down"] = None
        for s in self._swipes:
            self._raw(control.ACTION_UP, s["pid"], *s["to"])
        for pid, _m, pos in self._skills.values():
            self._raw(control.ACTION_UP, pid, *pos)
        self._skills = {}
        self._held.clear()
        if self._aim_pos is not None:
            self._raw(control.ACTION_UP, self._aim_pid, *self._aim_pos)
            self._aim_pos = None
        self._swipes = []
        self.set_aim_active(False)

    # ----- internals -----------------------------------------------------

    def _touch(self, action, pid, x, y, gap=0.0, coalesce=True):
        """Send a touch now, or queue it so that the finger behaves like a
        real one (see TOUCH_STEP). Events of one finger keep their order.
        gap: at least this long after the previous event of this finger.
        coalesce: a move replaces a move still waiting in the queue, so mouse
        motion never piles up."""
        now = self._clock()
        q = self._queue.setdefault(pid, [])
        due = now
        if q and gap:
            due = q[-1][0] + gap
        if action == control.ACTION_MOVE:
            due = max(due, self._down_at.get(pid, -1.0) + TOUCH_STEP)
            if coalesce and q and q[-1][1] == control.ACTION_MOVE:
                q[-1][2], q[-1][3] = x, y
                return
        elif action == control.ACTION_UP:
            due = max(due, self._down_at.get(pid, -1.0) + MIN_HOLD)
        elif action == control.ACTION_DOWN:
            due = max(due, self._up_at.get(pid, -1.0) + REPRESS_GAP)
        if q:
            due = max(due, q[-1][0])
        if action == control.ACTION_DOWN:
            self._down_at[pid] = due
        elif action == control.ACTION_UP:
            self._up_at[pid] = due
        if due <= now and not q:
            self._raw(action, pid, x, y)
        else:
            q.append([due, action, x, y])

    def _start_swipe(self, i, m):
        pid = MAPPING_POINTER_BASE + i
        if any(s["pid"] == pid for s in self._swipes):
            return
        x0, y0 = m["from"]
        self._touch(control.ACTION_DOWN, pid, x0, y0)
        self._swipes.append({
            "pid": pid, "from": tuple(m["from"]), "to": tuple(m["to"]),
            "start": self._clock(), "duration": float(m.get("duration", 150)) / 1000.0,
        })

    def _update_joystick(self, i, m):
        st = self._joy_state[i]
        p = st["pressed"]
        vx = (1 if "right" in p else 0) - (1 if "left" in p else 0)
        vy = (1 if "down" in p else 0) - (1 if "up" in p else 0)
        pid = JOYSTICK_POINTER_BASE + i
        cx, cy = m["x"], m["y"]
        if vx == 0 and vy == 0:
            if st["down"]:
                self._touch(control.ACTION_UP, pid, *st["down"])
                st["down"] = None
            return
        norm = math.hypot(vx, vy)
        scale = float(m.get("radius", 0.12)) * (0.5 if st["walk"] else 1.0)
        aspect = self._aspect() or 1.0
        tx = _clamp01(cx + vx / norm * scale / aspect)
        ty = _clamp01(cy + vy / norm * scale)
        if not st["down"]:
            self._touch(control.ACTION_DOWN, pid, cx, cy)
            # Down, then half way one step later, then the full deflection:
            # the game sees the touch start at the center and then drag.
            self._touch(control.ACTION_MOVE, pid, (cx + tx) / 2, (cy + ty) / 2, coalesce=False)
            self._touch(control.ACTION_MOVE, pid, tx, ty, gap=TOUCH_STEP, coalesce=False)
        else:
            self._touch(control.ACTION_MOVE, pid, tx, ty)
        st["down"] = (tx, ty)


def new_profile(name, directory):
    base = slugify(name)
    path = os.path.join(directory, base + ".json")
    n = 2
    while os.path.exists(path):
        path = os.path.join(directory, "%s_%d.json" % (base, n))
        n += 1
    return Profile(name, [], [], path)


def clone_profile(profile):
    return Profile(profile.name, copy.deepcopy(profile.mappings), list(profile.packages), profile.path)

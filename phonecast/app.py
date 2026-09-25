"""The desktop window: shows the phone screen, forwards input, runs key mapping."""

import os
import shutil
import subprocess
import sys
import threading
import time

import numpy

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from . import control, hid, keys  # noqa: E402
from .editor import PANEL_W, Editor  # noqa: E402
from .keymap import Engine, new_profile  # noqa: E402
from .media import AudioPlayer, VideoDecoder, find_audio_player  # noqa: E402

MOUSE_POINTER_ID = 0

HELP_LINES = [
    "F1   — эта справка",
    "Alt  — в игре: бой / меню (в меню мышь и клавиатура работают как обычно)",
    "F2   — включить / выключить раскладку игры",
    "F3   — настроить управление (как в BlueStacks)",
    "F4   — показать / скрыть подсказки кнопок",
    "F5   — следующий профиль раскладки",
    "F6   — недавние приложения        F7 — шторка уведомлений",
    "F8 / F9 — громкость − / +          F10 — экран телефона вкл/выкл",
    "F11  — полный экран",
    "F12  — ПК-режим: телефон видит клавиатуру и мышь (Minecraft и др.)",
    "ЛКМ — касание, ПКМ — «Назад», СКМ — «Домой», колесо — прокрутка",
    "Ctrl+V — вставить текст из буфера обмена ПК",
    "В режиме прицела мышь захвачена: клавиша прицела отпускает её",
]


def _font(size, bold=False):
    for name in ("dejavusans", "notosans", "liberationsans", "freesans", "ubuntu"):
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, int(size * 1.3))


def read_pc_clipboard():
    for cmd in (["wl-paste", "-n"], ["xclip", "-o", "-selection", "clipboard"], ["xsel", "-ob"]):
        if shutil.which(cmd[0]):
            try:
                out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     timeout=2).stdout
                return out.decode("utf-8", errors="replace")
            except (OSError, subprocess.TimeoutExpired):
                continue
    return None


class App:
    def __init__(self, session, adb, profiles, profiles_dir, start_profile=None,
                 fullscreen=False, audio=True, screen_off=False, pc_mode_apps=()):
        self.session = session
        self.adb = adb
        self.profiles = profiles
        self.profiles_dir = profiles_dir
        self.fullscreen = fullscreen
        self.want_audio = audio
        self.screen_off_at_start = screen_off

        self.engine = Engine(self.touch_norm, self.press_keycode, self.aspect)
        self.profile_index = 0
        if start_profile:
            for i, p in enumerate(profiles):
                if start_profile in (p.name, os.path.basename(p.path or "")):
                    self.profile_index = i
        if profiles:
            self.engine.set_profile(profiles[self.profile_index])

        self.keymap_on = False
        self.auto_keymap = False  # keymap was enabled automatically for an app
        self.show_hints = True
        self.show_help = False
        self.editor = None
        self.phone_screen_on = True

        self.running = True
        self.device_gone = False
        self.frame_surface = None
        self._scaled = None
        self._hints_cache = None
        self.dirty = True
        self.frame_native = (0, 0)
        self.view = pygame.Rect(0, 0, 0, 0)
        self.mouse_down = False
        self.forwarded_keys = set()
        self.grabbed = False
        self.toasts = []  # [(text, expire_time)]

        self.fg_package = None
        self._fg_seen = None

        # PC mode: virtual USB keyboard + mouse on the phone (see hid.py)
        self.pc_mode = False
        self.pc_mode_apps = set(pc_mode_apps)  # apps that switch PC mode on by themselves
        self.auto_pc_mode = False
        self.hid_keyboard = hid.Keyboard()
        self.hid_mouse = hid.Mouse()
        self._motion = [0, 0]   # mouse motion accumulated during one loop iteration
        self.focused = True

        self.quit_requested = False   # the user closed the window
        self.panel_w = 0              # width of the editor panel while it is open
        self.menu_mode = False        # game mapping paused with Alt to use the game menus
        self._alt_alone = False
        self._gear_rect = None
        self.stats = {"decoded": 0, "shown": 0, "lag": 0}
        self._shown = 0

    # ----- helpers used by the key mapping engine ------------------------

    def aspect(self):
        w, h = self.decoder.frame_size
        return w / h if h else 1.0

    def touch_norm(self, action, pointer_id, nx, ny):
        w, h = self.decoder.frame_size
        if not w:
            return
        x = min(max(round(nx * w), 0), w - 1)
        y = min(max(round(ny * h), 0), h - 1)
        self.session.send(control.inject_touch(action, pointer_id, x, y, w, h))

    def press_keycode(self, keycode, meta=0):
        self.session.send(control.inject_keycode(control.KEY_DOWN, keycode, 0, meta))
        self.session.send(control.inject_keycode(control.KEY_UP, keycode, 0, meta))

    def toast(self, text, seconds=2.5):
        self.toasts = [t for t in self.toasts if t[0] != text][-3:]
        self.toasts.append((text, time.monotonic() + seconds))

    @property
    def profile(self):
        return self.engine.profile

    # ----- coordinates ---------------------------------------------------

    def window_to_norm(self, pos):
        if not self.view.w:
            return None
        nx = (pos[0] - self.view.x) / self.view.w
        ny = (pos[1] - self.view.y) / self.view.h
        return nx, ny

    def norm_to_window(self, nx, ny):
        return (int(self.view.x + nx * self.view.w), int(self.view.y + ny * self.view.h))

    def inside_view(self, pos):
        return self.view.collidepoint(pos)

    # ----- window --------------------------------------------------------

    def _fit_window_size(self, fw, fh):
        info = self.desktop_size
        max_w, max_h = int(info[0] * 0.9), int(info[1] * 0.85)
        scale = min(max_w / fw, max_h / fh)
        return max(200, int(fw * scale)), max(200, int(fh * scale))

    def _set_mode(self, size=None):
        if self.fullscreen:
            self.screen = pygame.display.set_mode(self.desktop_size, pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(size or self.window_size, pygame.RESIZABLE)
            self.window_size = self.screen.get_size()
        self._layout()

    def _layout(self):
        sw, sh = self.screen.get_size()
        sw -= self.panel_w  # the editor panel sits right of the phone picture
        fw, fh = self.frame_native if self.frame_native[0] else self.session.initial_size
        scale = min(sw / fw, sh / fh)
        w, h = int(fw * scale), int(fh * scale)
        self.view = pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h)
        self._scaled = None
        self._hints_cache = None
        self.dirty = True

    def _update_title(self):
        mode = "игровой режим" if self.keymap_on else "обычный режим"
        if self.editor:
            mode = "редактор"
        if self.pc_mode:
            mode = "ПК-режим"
        prof = " · " + self.profile.name if self.profile else ""
        pygame.display.set_caption("Phonecast — %s — %s%s" % (self.session.device_name, mode, prof))

    # ----- main loop -----------------------------------------------------

    def run(self):
        pygame.init()
        pygame.key.set_repeat()  # no auto-repeat: games need clean down/up pairs
        try:
            self.desktop_size = pygame.display.get_desktop_sizes()[0]
        except (AttributeError, IndexError, pygame.error):
            info = pygame.display.Info()
            self.desktop_size = (info.current_w or 1280, info.current_h or 720)
        self.font = _font(16)
        self.font_small = _font(13, bold=True)
        self.font_big = _font(18, bold=True)

        self.decoder = VideoDecoder(self.session.video_sock, on_eof=self._on_device_gone,
                                    request_keyframe=self._request_keyframe)
        self.frame_native = self.session.initial_size
        self.window_size = self._fit_window_size(*self.frame_native)
        self._set_mode()
        self._update_title()
        self.decoder.start()

        if self.session.audio_sock:
            player = find_audio_player()
            if player:
                AudioPlayer(self.session.audio_sock, player, self.session.audio_codec).start()
            else:
                print("phonecast: no audio player found (pacat/pw-cat/aplay), audio disabled",
                      file=sys.stderr)
                threading.Thread(target=AudioPlayer(self.session.audio_sock, None)._drain,
                                 daemon=True).start()
        threading.Thread(target=self.session.drain_device_messages, daemon=True).start()
        threading.Thread(target=self._watch_foreground, daemon=True).start()

        if self.screen_off_at_start:
            self.toggle_phone_screen()
        pygame.key.start_text_input()
        self.toast("F1 — справка по управлению", 5)

        clock = pygame.time.Clock()
        last_draw = 0.0
        stats_t, stats_frames = time.monotonic(), 0
        try:
            while self.running:
                events = pygame.event.get()
                for event in events:
                    self.handle_event(event)
                self._flush_pc_motion()
                if time.monotonic() - stats_t >= 1.0:
                    self.stats = {"decoded": self.decoder.frame_count - stats_frames,
                                  "shown": self._shown, "lag": self.decoder.lag_ms}
                    stats_t, stats_frames, self._shown = time.monotonic(), self.decoder.frame_count, 0
                    if self.show_help:
                        self.dirty = True
                self._poll_foreground()
                self.engine.update()
                self._sync_grab()
                self._check_lag()
                now = time.monotonic()
                new_frame = self._take_frame()
                # Redraw only when something changed; toasts need an occasional
                # refresh to disappear on time.
                if new_frame or events or self.dirty or (self.toasts and now - last_draw > 0.1):
                    self._draw()
                    last_draw = now
                    self.dirty = False
                    if new_frame:
                        self._shown += 1
                clock.tick(250)
        finally:
            self.engine.release_all()
            if self.pc_mode:
                self.set_pc_mode(False)
            if not self.phone_screen_on:
                self.session.send(control.set_display_power(True))
            time.sleep(0.1)
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)

    def _request_keyframe(self):
        # Called from the decoder thread when it fell behind the stream.
        self.session.send(control.reset_video())

    def _check_lag(self):
        drops = self.decoder.drop_count
        if drops != getattr(self, "_drops_seen", 0):
            self._drops_seen = drops
            now = time.monotonic()
            self._drop_times = [t for t in getattr(self, "_drop_times", []) if now - t < 30] + [now]
            if len(self._drop_times) >= 3 and not getattr(self, "_slow_warned", False):
                # Only a hint: reconnecting on our own is worse than a skipped frame.
                self._slow_warned = True
                self.toast("Видео не успевает: уменьшите max_size или bit_rate в "
                           "~/.config/phonecast/settings.json", 8)

    def _on_device_gone(self):
        self.device_gone = True
        self.running = False

    # ----- drawing -------------------------------------------------------

    def _take_frame(self):
        """Convert the newest decoded frame (if any) for display.

        Only the frame that will be shown is converted; the conversion is done
        at native size (cheap) and scaling is left to pygame (also cheap),
        which is much faster than letting swscale do both at once.
        """
        frame = self.decoder.take_frame()
        if frame is None:
            return False
        native = (frame.width, frame.height)
        if native != self.frame_native:
            old = self.frame_native
            self.frame_native = native
            rotated = (old[0] > old[1]) != (native[0] > native[1])
            if rotated and not self.fullscreen:
                self._set_mode(self._fit_window_size(*native))
            else:
                self._layout()
        # Rows may be padded in memory (e.g. width 1080), pygame needs them packed:
        # ascontiguousarray copies only in that case.
        rgb = numpy.ascontiguousarray(frame.to_ndarray(format="rgb24"))
        self.frame_surface = pygame.image.frombuffer(rgb, native, "RGB")
        self._frame_buffer = rgb  # keep the pixels alive as long as the surface
        self._scaled = None
        return True

    def _draw(self):
        self.screen.fill((0, 0, 0))
        if self.frame_surface:
            if self._scaled is None:
                surf = self.frame_surface
                if surf.get_size() != self.view.size:
                    surf = pygame.transform.scale(surf, self.view.size)
                self._scaled = surf
            self.screen.blit(self._scaled, self.view.topleft)
        else:
            self._text_center("Ожидание изображения с телефона…")

        if self.editor:
            self.editor.draw(self.screen)
        elif self.keymap_on and self.show_hints and self.profile:
            key = (id(self.profile), repr(self.profile.mappings), self.screen.get_size())
            if self._hints_cache is None or self._hints_cache[0] != key:
                layer = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
                self.draw_mappings(layer, alpha=110)
                self._hints_cache = (key, layer)
            self.screen.blit(self._hints_cache[1], (0, 0))

        self._draw_status()
        if self.show_help:
            self._draw_help()
        self._draw_toasts()
        pygame.display.flip()

    def _text_center(self, text):
        img = self.font_big.render(text, True, (220, 220, 220))
        self.screen.blit(img, img.get_rect(center=self.screen.get_rect().center))

    def label(self, surface, text, center, color=(255, 255, 255), bg=(0, 0, 0, 170)):
        img = self.font_small.render(text, True, color)
        r = img.get_rect(center=center).inflate(10, 6)
        box = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(box, bg, box.get_rect(), border_radius=6)
        surface.blit(box, r.topleft)
        surface.blit(img, img.get_rect(center=center))
        return r

    def draw_mappings(self, surface, alpha=160, selected=None, labels=True):
        if not self.profile:
            return
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        fh = self.view.h
        for i, m in enumerate(self.profile.mappings):
            t = m["type"]
            col = (255, 210, 0, alpha) if i == selected else (0, 200, 255, alpha)
            if t == "tap":
                c = self.norm_to_window(m["x"], m["y"])
                pygame.draw.circle(overlay, col, c, 20, 3)
            elif t == "joystick":
                c = self.norm_to_window(m["x"], m["y"])
                r = int(float(m.get("radius", 0.12)) * fh)
                pygame.draw.circle(overlay, col, c, max(r, 10), 3)
                pygame.draw.circle(overlay, col, c, 6)
            elif t == "aim":
                c = self.norm_to_window(m["x"], m["y"])
                r = int(float(m.get("radius", 0.3)) * fh)
                pygame.draw.circle(overlay, col[:3] + (alpha // 2,), c, max(r, 10), 2)
                pygame.draw.line(overlay, col, (c[0] - 14, c[1]), (c[0] + 14, c[1]), 3)
                pygame.draw.line(overlay, col, (c[0], c[1] - 14), (c[0], c[1] + 14), 3)
            elif t == "skill":
                c = self.norm_to_window(m["x"], m["y"])
                r = int(float(m.get("radius", 0.1)) * fh)
                pygame.draw.circle(overlay, col, c, max(r, 12), 3)
                pygame.draw.circle(overlay, col[:3] + (alpha // 3,), c, max(r, 12))
            elif t == "swipe":
                a = self.norm_to_window(*m["from"])
                b = self.norm_to_window(*m["to"])
                pygame.draw.line(overlay, col, a, b, 3)
                pygame.draw.circle(overlay, col, b, 7)
                pygame.draw.circle(overlay, col, a, 16, 3)
        surface.blit(overlay, (0, 0))
        if not labels:
            return
        # Keys bound to the same point (e.g. Brawl Stars: LMB aimed attack and
        # Space quick attack) share one label instead of hiding each other.
        point_labels = {}
        for m in self.profile.mappings:
            if m["type"] in ("tap", "skill", "swipe"):
                pos = self.norm_to_window(*(m["from"] if m["type"] == "swipe" else (m["x"], m["y"])))
                text = keys.pretty(m["key"]) + (" →" if m["type"] == "skill" else "")
                point_labels.setdefault(pos, []).append(text)
        for pos, texts in point_labels.items():
            self.label(surface, " / ".join(texts), pos)
        for i, m in enumerate(self.profile.mappings):
            t = m["type"]
            if t == "joystick":
                cx, cy = self.norm_to_window(m["x"], m["y"])
                r = int(float(m.get("radius", 0.12)) * fh)
                for d, (ox, oy) in (("up", (0, -1)), ("down", (0, 1)), ("left", (-1, 0)), ("right", (1, 0))):
                    self.label(surface, keys.pretty(m[d]), (cx + ox * r, cy + oy * r))
            elif t == "aim":
                cx, cy = self.norm_to_window(m["x"], m["y"])
                self.label(surface, "прицел: " + keys.pretty(m["toggle"]), (cx, cy + 30))

    def _draw_status(self):
        parts = []
        if self.editor:
            return
        if self.pc_mode:
            parts.append("ПК-РЕЖИМ: клавиатура и мышь подключены к телефону · F12 — выйти")
        if self.keymap_on:
            parts.append("БОЙ" + (" · " + self.profile.name if self.profile else ""))
            if self.engine.aim_active:
                parts.append("мышь захвачена (%s — отпустить)" % keys.pretty(self.engine.aim["toggle"]))
            parts.append("Alt — меню")
        elif self.menu_mode and self.profile:
            parts.append("МЕНЮ · %s · Alt — в бой" % self.profile.name)
        if not self.phone_screen_on:
            parts.append("экран телефона выкл.")
        if parts:
            self.label(self.screen, "  ·  ".join(parts), (self.screen.get_width() // 2, 16),
                       color=(255, 230, 120))
        # "Configure controls" button: shown while the free cursor is near the top.
        self._gear_rect = None
        if not self.pc_mode and not self.grabbed and pygame.mouse.get_focused() \
                and pygame.mouse.get_pos()[1] < 70:
            self._gear_rect = self.label(self.screen, "⚙ Настроить управление (F3)",
                                         (self.screen.get_width() - 120, 44),
                                         color=(255, 255, 255), bg=(40, 110, 200, 235))

    def _draw_help(self):
        st = self.stats
        w, h = self.frame_native
        lines = HELP_LINES + [
            "",
            "Видео %dx%d · принято %d к/с · показано %d к/с · отставание %d мс"
            % (w, h, st["decoded"], st["shown"], st["lag"]),
        ]
        w = max(self.font.size(line)[0] for line in lines) + 40
        h = len(lines) * 24 + 30
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(box, (10, 10, 20, 225), box.get_rect(), border_radius=10)
        for i, line in enumerate(lines):
            box.blit(self.font.render(line, True, (235, 235, 235)), (20, 15 + i * 24))
        self.screen.blit(box, box.get_rect(center=self.screen.get_rect().center))

    def _draw_toasts(self):
        now = time.monotonic()
        self.toasts = [t for t in self.toasts if t[1] > now]
        y = self.screen.get_height() - 24
        for text, _ in reversed(self.toasts):
            r = self.label(self.screen, text, (self.screen.get_width() // 2, y), bg=(0, 0, 0, 200))
            y -= r.h + 6

    # ----- events --------------------------------------------------------

    def handle_event(self, ev):
        if ev.type == pygame.QUIT:
            self.quit_requested = True
            self.running = False
            return
        if ev.type == pygame.VIDEORESIZE and not self.fullscreen:
            self.window_size = (ev.w, ev.h)
            self._layout()
            return
        if ev.type in (pygame.WINDOWSIZECHANGED,):
            self._layout()
            return
        if ev.type == pygame.WINDOWFOCUSLOST:
            self.focused = False
            self._release_everything()
            return
        if ev.type == pygame.WINDOWFOCUSGAINED:
            self.focused = True
            return
        if self.pc_mode:
            self._pc_event(ev)
            return

        if ev.type == pygame.KEYDOWN:
            name = keys.key_name(ev.scancode, pygame.key.name(ev.key))
            if self._hotkey(name):
                return
        if self.editor:
            if self.editor.handle_event(ev):
                return
            return  # nothing reaches the phone while editing

        # Left Alt pressed and released alone: battle <-> menu (like emulators).
        # Alt+Tab, Alt+Shift... do not count.
        if ev.type == pygame.KEYDOWN:
            name = keys.key_name(ev.scancode, pygame.key.name(ev.key))
            if name == "lalt" and not self.engine.handles("lalt") and (self.keymap_on or self.menu_mode):
                self._alt_alone = True
                return
            self._alt_alone = False
        elif ev.type == pygame.KEYUP and keys.key_name(ev.scancode, pygame.key.name(ev.key)) == "lalt" \
                and self._alt_alone:
            self._alt_alone = False
            self.toggle_battle()
            return
        elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL):
            self._alt_alone = False
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self._gear_rect \
                and self._gear_rect.collidepoint(ev.pos) and not self.grabbed:
            self.toggle_editor()
            return

        if ev.type == pygame.KEYDOWN:
            self._key_down(ev, keys.key_name(ev.scancode, pygame.key.name(ev.key)))
        elif ev.type == pygame.KEYUP:
            self._key_up(keys.key_name(ev.scancode, pygame.key.name(ev.key)))
        elif ev.type == pygame.TEXTINPUT:
            if not self.keymap_on and ev.text:
                self.session.send(control.inject_text(ev.text))
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            self._mouse_button(ev, True)
        elif ev.type == pygame.MOUSEBUTTONUP:
            self._mouse_button(ev, False)
        elif ev.type == pygame.MOUSEMOTION:
            if self.engine.aim_active:
                self.engine.mouse_motion(*ev.rel)
            elif self.keymap_on and self.view.w:
                self.engine.mouse_position(*self.window_to_norm(ev.pos))
            if not self.engine.aim_active and self.mouse_down:
                self._send_mouse_touch(control.ACTION_MOVE, ev.pos)
        elif ev.type == pygame.MOUSEWHEEL:
            if not self.engine.aim_active:
                pos = pygame.mouse.get_pos()
                if self.inside_view(pos):
                    fx, fy, w, h = self._frame_point(pos)
                    self.session.send(control.inject_scroll(
                        fx, fy, w, h, getattr(ev, "precise_x", ev.x), getattr(ev, "precise_y", ev.y)))

    def _hotkey(self, name):
        if name == "f1":
            self.show_help = not self.show_help
        elif name == "f2":
            self.set_keymap(not self.keymap_on)
        elif name == "f3":
            self.toggle_editor()
        elif name == "f4":
            self.show_hints = not self.show_hints
        elif name == "f5":
            self.next_profile()
        elif name == "f6":
            self.press_keycode(keys.KEYCODE_APP_SWITCH)
        elif name == "f7":
            self.session.send(control.expand_notification_panel())
        elif name == "f8":
            self.press_keycode(keys.KEYCODE_VOLUME_DOWN)
        elif name == "f9":
            self.press_keycode(keys.KEYCODE_VOLUME_UP)
        elif name == "f10":
            self.toggle_phone_screen()
        elif name == "f11":
            self._release_everything()
            self.fullscreen = not self.fullscreen
            self._set_mode()
        elif name == "f12":
            self.set_pc_mode(not self.pc_mode)
        else:
            return False
        return True

    def _key_down(self, ev, name):
        if self.keymap_on and self.engine.key_down(name):
            return
        mods = ev.mod
        meta = 0
        if mods & pygame.KMOD_CTRL:
            meta |= keys.META_CTRL_ON
        if mods & pygame.KMOD_SHIFT:
            meta |= keys.META_SHIFT_ON
        if mods & pygame.KMOD_ALT:
            meta |= keys.META_ALT_ON

        if not self.keymap_on:
            if (mods & pygame.KMOD_CTRL) and name == "v":
                text = read_pc_clipboard()
                if text:
                    self.session.send(control.set_clipboard(text, paste=True))
                else:
                    self.toast("Не удалось прочитать буфер обмена (нужен wl-paste или xclip)")
                return
            # Printable keys arrive as TEXTINPUT, except with Ctrl/Alt held.
            if name not in keys.NON_TEXT_KEYS and not (mods & (pygame.KMOD_CTRL | pygame.KMOD_ALT)):
                return
        if self.engine.aim_active:
            return
        code = keys.ANDROID_KEYCODES.get(name)
        if code is not None:
            self.forwarded_keys.add(name)
            self.session.send(control.inject_keycode(control.KEY_DOWN, code, 0, meta))

    def _key_up(self, name):
        if self.keymap_on and self.engine.key_up(name):
            return
        if name in self.forwarded_keys:
            self.forwarded_keys.discard(name)
            self.session.send(control.inject_keycode(control.KEY_UP, keys.ANDROID_KEYCODES[name]))

    def _mouse_button(self, ev, down):
        name = keys.MOUSE_BUTTON_NAMES.get(ev.button)
        if name is None:
            return
        # With a free cursor the left button stays a normal touch (menus),
        # unless the profile uses it for an aimed skill (Brawl Stars attack).
        if self.keymap_on and self.engine.handles(name) and (
                self.engine.aim_active or name != "mouse_left"
                or self.engine.mapping_type(name) == "skill"):
            if down and not self.engine.aim_active and self.view.w:
                self.engine.mouse_position(*self.window_to_norm(ev.pos))
            if down:
                self.engine.key_down(name)
            else:
                self.engine.key_up(name)
            return
        if self.engine.aim_active:
            return
        if name == "mouse_left":
            if down and self.inside_view(ev.pos):
                self.mouse_down = True
                self._send_mouse_touch(control.ACTION_DOWN, ev.pos)
            elif not down and self.mouse_down:
                self.mouse_down = False
                self._send_mouse_touch(control.ACTION_UP, ev.pos)
        elif name == "mouse_right":
            # Back, or wake the screen if it is off.
            self.session.send(control.back_or_screen_on(control.KEY_DOWN if down else control.KEY_UP))
        elif name == "mouse_middle" and down:
            self.press_keycode(keys.KEYCODE_HOME)

    def _frame_point(self, pos):
        w, h = self.decoder.frame_size
        if not w:
            w, h = self.frame_native
        nx, ny = self.window_to_norm(pos)
        x = min(max(int(nx * w), 0), w - 1)
        y = min(max(int(ny * h), 0), h - 1)
        return x, y, w, h

    def _send_mouse_touch(self, action, pos):
        if not self.decoder.frame_size[0]:
            return
        x, y, w, h = self._frame_point(pos)
        self.session.send(control.inject_touch(action, MOUSE_POINTER_ID, x, y, w, h))

    def _release_everything(self):
        self.engine.release_all()
        self._motion = [0, 0]
        for report in (self.hid_keyboard.release_all(), self.hid_mouse.release_all()):
            if report and self.pc_mode:
                self.session.send(control.uhid_input(
                    hid.KEYBOARD_ID if len(report) == 8 else hid.MOUSE_ID, report))
        if self.mouse_down:
            self.mouse_down = False
            self._send_mouse_touch(control.ACTION_UP, pygame.mouse.get_pos())
        for name in list(self.forwarded_keys):
            self._key_up(name)

    def _sync_grab(self):
        want = self.engine.aim_active or (self.pc_mode and self.focused)
        if want != self.grabbed:
            self.grabbed = want
            pygame.event.set_grab(want)
            pygame.mouse.set_visible(not want)
            pygame.mouse.get_rel()
            if want and self.engine.aim_active:
                self.toast("Мышь захвачена для прицела. %s — отпустить, F2 — выключить раскладку"
                           % keys.pretty(self.engine.aim["toggle"]), 4)

    # ----- PC mode (virtual keyboard + mouse) -----------------------------

    def set_pc_mode(self, on):
        self.auto_pc_mode = False
        if on == self.pc_mode:
            return
        if on:
            if self.editor:
                self.toggle_editor()
            if self.keymap_on:
                self.set_keymap(False)
            self._release_everything()
            pygame.key.stop_text_input()
            self.session.send(control.uhid_create(hid.KEYBOARD_ID, hid.KEYBOARD_REPORT_DESC,
                                                  "Phonecast Keyboard"))
            self.session.send(control.uhid_create(hid.MOUSE_ID, hid.MOUSE_REPORT_DESC,
                                                  "Phonecast Mouse"))
            self.pc_mode = True
            self.toast("ПК-режим: телефон видит клавиатуру и мышь. F12 — выйти", 5)
        else:
            self._release_everything()
            self.session.send(control.uhid_destroy(hid.KEYBOARD_ID))
            self.session.send(control.uhid_destroy(hid.MOUSE_ID))
            self.pc_mode = False
            pygame.key.start_text_input()
            self.toast("ПК-режим выключен")
        self._update_title()
        self.dirty = True

    def _pc_event(self, ev):
        if ev.type in (pygame.KEYDOWN, pygame.KEYUP):
            name = keys.key_name(ev.scancode, pygame.key.name(ev.key))
            if ev.type == pygame.KEYDOWN and name in ("f11", "f12"):
                # the only keys kept by the program; all others go to the phone
                self._hotkey(name)
                return
            report = (self.hid_keyboard.press(ev.scancode) if ev.type == pygame.KEYDOWN
                      else self.hid_keyboard.release(ev.scancode))
            if report:
                self.session.send(control.uhid_input(hid.KEYBOARD_ID, report))
        elif ev.type == pygame.MOUSEMOTION:
            if self.grabbed:
                self._motion[0] += ev.rel[0]
                self._motion[1] += ev.rel[1]
        elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            self._flush_pc_motion()
            report = self.hid_mouse.button(ev.button, ev.type == pygame.MOUSEBUTTONDOWN)
            if report:
                self.session.send(control.uhid_input(hid.MOUSE_ID, report))
        elif ev.type == pygame.MOUSEWHEEL:
            self._flush_pc_motion()
            report = self.hid_mouse.wheel(ev.y, ev.x)
            if report:
                self.session.send(control.uhid_input(hid.MOUSE_ID, report))

    def _flush_pc_motion(self):
        # Motion is sent once per loop iteration instead of once per OS event:
        # far fewer messages with a high-rate gaming mouse, same total movement.
        dx, dy = self._motion
        if dx or dy:
            self._motion = [0, 0]
            for report in self.hid_mouse.motion(dx, dy):
                self.session.send(control.uhid_input(hid.MOUSE_ID, report))

    # ----- modes ---------------------------------------------------------

    def toggle_battle(self):
        """Alt: pause the game mapping to use menus, and back."""
        if self.keymap_on:
            auto = self.auto_keymap
            self.set_keymap(False)
            self.auto_keymap = auto   # still leave the mapping off when the game is left
            self.menu_mode = True
            self.toast("Меню: мышь и клавиатура работают как обычно. Alt — вернуться в бой", 4)
        elif self.profile:
            self.set_keymap(True, auto=self.auto_keymap)
        self._update_title()

    def set_keymap(self, on, auto=False):
        self.menu_mode = False
        if on and self.pc_mode:
            self.set_pc_mode(False)
        if on and not self.profile:
            self.toast("Нет профиля раскладки — создайте его в редакторе (F3)")
            return
        self._release_everything()
        self.keymap_on = on
        self.auto_keymap = auto and on
        if on:
            pygame.key.stop_text_input()
            if self.engine.aim and self.engine.aim.get("auto"):
                self.engine.set_aim_active(True)  # shooters: mouse look right away
            self.toast("Бой: %s. Alt — меню, F3 — настроить кнопки" % self.profile.name, 5)
        else:
            pygame.key.start_text_input()
            self.toast("Обычный режим (ввод текста)")
        self._update_title()

    def next_profile(self):
        if not self.profiles:
            self.toast("Профилей нет — создайте в редакторе (F3)")
            return
        self.profile_index = (self.profile_index + 1) % len(self.profiles)
        self.use_profile(self.profile_index)

    def use_profile(self, index):
        self._release_everything()
        self.profile_index = index
        self.engine.set_profile(self.profiles[index])
        self.toast("Профиль: %s" % self.profile.name)
        self._update_title()

    def add_profile(self, name, package=None):
        p = new_profile(name, self.profiles_dir)
        if package:
            p.packages.append(package)
        self.profiles.append(p)
        self.use_profile(len(self.profiles) - 1)
        return p

    def toggle_editor(self, save=True):
        self._release_everything()
        if self.editor:
            self.editor.close(save=save)
            self.editor = None
            self._set_panel(0)
            if self.keymap_on:
                pygame.key.stop_text_input()
                if self.engine.aim and self.engine.aim.get("auto"):
                    self.engine.set_aim_active(True)
            else:
                pygame.key.start_text_input()
            self.toast("Управление сохранено" if save else "Изменения отменены")
        else:
            if not self.profile:
                self.add_profile(self.fg_package or "Default", self.fg_package)
            self.editor = Editor(self)
            pygame.key.stop_text_input()
            self._set_panel(PANEL_W)
        self._update_title()
        self.dirty = True

    def _set_panel(self, width):
        """Widen the window by the editor panel (or give the room back)."""
        delta = width - self.panel_w
        self.panel_w = width
        if not self.fullscreen and delta:
            w, h = self.screen.get_size()
            self._set_mode((max(300, w + delta), h))
        else:
            self._layout()

    def toggle_phone_screen(self):
        self.phone_screen_on = not self.phone_screen_on
        self.session.send(control.set_display_power(self.phone_screen_on))
        self.toast("Экран телефона включён" if self.phone_screen_on
                   else "Экран телефона выключен (трансляция продолжается)")

    # ----- per-app profiles ----------------------------------------------

    def _watch_foreground(self):
        while self.running:
            try:
                self.fg_package = self.adb.foreground_package()
            except Exception:  # adb hiccups must never kill the app
                pass
            time.sleep(2)

    def _poll_foreground(self):
        pkg = self.fg_package
        if pkg == self._fg_seen:
            return
        self._fg_seen = pkg
        if self.editor or not pkg:
            return
        if pkg in self.pc_mode_apps:
            if not self.pc_mode:
                self.set_pc_mode(True)
                self.auto_pc_mode = True
            return
        if self.auto_pc_mode:
            self.set_pc_mode(False)
        if self.pc_mode:
            return
        for i, p in enumerate(self.profiles):
            if pkg in p.packages:
                if i != self.profile_index or not self.keymap_on:
                    self.use_profile(i)
                    self.set_keymap(True, auto=True)
                return
        if self.auto_keymap or self.menu_mode:
            self.set_keymap(False)
            self.auto_keymap = False

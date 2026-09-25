"""The application window around mirroring sessions.

Waits for the phone with friendly instructions, starts a session, returns to
waiting (and reconnects) when the cable is pulled, until the window is closed.
"""

import math
import os
import sys
import threading
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# Window class used by the desktop entry (StartupWMClass) to group the window.
os.environ.setdefault("SDL_VIDEO_X11_WMCLASS", "phonecast")
os.environ.setdefault("SDL_VIDEO_WAYLAND_WMCLASS", "phonecast")
import pygame  # noqa: E402

from . import settings as settings_mod  # noqa: E402
from . import theme  # noqa: E402
from .adb import Adb, AdbError  # noqa: E402
from .app import App, _font  # noqa: E402
from .keymap import load_profiles  # noqa: E402
from .settings_panel import SettingsPanel, is_chord  # noqa: E402
from .session import Session, SessionError  # noqa: E402

ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")

CHECKLIST = [
    "1. Подключите телефон кабелем, который передаёт данные.",
    "2. На телефоне: Параметры разработчика → «Отладка по USB» включена.",
    "3. Chromebook: нажмите уведомление «Подключить к Linux»",
    "    (или Настройки → Разработчики → Linux → Управление USB-устройствами).",
    "4. Разблокируйте телефон и нажмите «Разрешить» в запросе отладки.",
]


def parse_bit_rate(text):
    text = str(text).strip().upper()
    mult = 1
    if text.endswith("M"):
        mult, text = 1_000_000, text[:-1]
    elif text.endswith("K"):
        mult, text = 1_000, text[:-1]
    return int(float(text) * mult)


class Launcher:
    def __init__(self, options, profiles_dir, serial=None, start_profile=None,
                 server_file=None, verbose=False, stay_awake=True):
        self.options = options          # merged settings + command line
        self.profiles_dir = profiles_dir
        self.serial = serial
        self.start_profile = start_profile
        self.server_file = server_file
        self.verbose = verbose
        self.stay_awake = stay_awake

        self.status = "Ищу телефон…"
        self.details = []
        self.message = ""               # e.g. "connection lost", shown above the status
        self._result = None
        self._lock = threading.Lock()

    # ----- main ----------------------------------------------------------

    def run(self):
        pygame.init()
        if os.path.exists(ICON):
            try:
                pygame.display.set_icon(pygame.image.load(ICON))
            except pygame.error:
                pass
        theme.apply(self.options.get("theme"))
        self._load_fonts()
        try:
            self.screen_long = max(pygame.display.get_desktop_sizes()[0])
        except (AttributeError, IndexError, pygame.error):
            self.screen_long = 1920
        try:
            while True:
                session, adb = self._wait_for_phone()
                if session is None:
                    return 0
                app = App(session, adb, load_profiles(self.profiles_dir), self.profiles_dir,
                          start_profile=self.start_profile,
                          fullscreen=self.options["fullscreen"],
                          audio=self.options["audio"],
                          screen_off=self.options["screen_off"],
                          pc_mode_apps=self.options["pc_mode_apps"],
                          mode=self.options.get("mode", "control"),
                          quality=self.options.get("quality", "balanced"),
                          show_hints=self.options.get("show_hints", False),
                          mouse_sensitivity=self.options.get("mouse_sensitivity", 0.6))
                try:
                    app.run()
                finally:
                    session.close()
                self.options["mode"] = "watch" if app.watch else "control"
                if app.quit_requested:
                    return 0
                if app.reconnect:
                    saved = settings_mod.load()
                    for key in ("quality", "audio", "mode", "show_hints", "fullscreen", "screen_off"):
                        self.options[key] = saved[key]
                    self.message = "Применяю настройки…"
                    continue
                self.message = "Связь с телефоном потеряна."
                print("phonecast: connection lost (%s)" % (app.decoder.error or "video stream ended"),
                      file=sys.stderr)
        finally:
            pygame.quit()

    def _load_fonts(self):
        self.font = _font(16)
        self.font_small = _font(14)
        self.font_title = _font(30, bold=True)
        self.font_status = _font(19, bold=True)

    def _setting_changed(self, key, value):
        if key == "theme":
            self._load_fonts()

    # ----- waiting screen ------------------------------------------------

    def _wait_for_phone(self):
        # Keep the current window (after a lost connection) instead of
        # closing and reopening a small one.
        screen = pygame.display.get_surface()
        if screen is None:
            screen = pygame.display.set_mode((880, 580), pygame.RESIZABLE)
        pygame.display.set_caption("Phonecast")
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        self._result = None
        self.status, self.details = "Ищу телефон…", []
        self.panel = None
        self._stop = False
        threading.Thread(target=self._connect_loop, daemon=True).start()
        clock = pygame.time.Clock()
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self._stop = True
                    return None, None
                if ev.type == pygame.VIDEORESIZE:
                    screen = pygame.display.set_mode((ev.w, ev.h), pygame.RESIZABLE)
                    continue
                if self.panel:
                    self.panel.handle_event(ev)
                    if self.panel.closed:
                        self.panel = None
                elif is_chord(ev):
                    self.panel = SettingsPanel(self.options, self.font, self.font_status,
                                               on_change=self._setting_changed)
            with self._lock:
                result = self._result
            if result:
                self.message = ""
                return result
            self._draw(screen)
            clock.tick(15)

    def _draw(self, screen):
        t = theme.T
        theme.fill_bg(screen)
        w, h = screen.get_size()
        now = time.monotonic()
        with self._lock:
            status, details = self.status, list(self.details)

        # a phone with rings spreading from it while searching
        y = 30
        phone = pygame.Rect(0, 0, 40, 68)
        phone.midtop = (w // 2, y + 14)
        rings = pygame.Surface((160, 160), pygame.SRCALPHA)
        for k in range(3):
            p = (now * 0.6 + k / 3) % 1.0
            r = int(34 + 42 * p)
            pygame.draw.circle(rings, t.accent + (int(150 * (1 - p)),), (80, 80), r, 2)
        screen.blit(rings, rings.get_rect(center=phone.center))
        pygame.draw.rect(screen, t.surface, phone, border_radius=min(9, t.radius_panel))
        pygame.draw.rect(screen, t.accent, phone, 3, border_radius=min(9, t.radius_panel))
        pygame.draw.line(screen, t.accent, (phone.centerx - 7, phone.y + 7), (phone.centerx + 7, phone.y + 7), 3)
        pygame.draw.circle(screen, t.accent, (phone.centerx, phone.bottom - 9), 3)
        y = phone.bottom + 30

        title = self.font_title.render(t.heading("Phonecast"), True, t.text)
        screen.blit(title, title.get_rect(midtop=(w // 2, y)))
        y += title.get_height() + 4
        sub = self.font_small.render("Экран телефона на ноутбуке по USB-кабелю", True, t.muted)
        screen.blit(sub, sub.get_rect(midtop=(w // 2, y)))
        y += sub.get_height() + 22

        if self.message:
            img = self.font.render(self.message, True, t.warn)
            pill = img.get_rect(midtop=(w // 2, y)).inflate(24, 10)
            pygame.draw.rect(screen, t.warn, pill, 1, border_radius=min(t.radius, pill.h // 2))
            screen.blit(img, img.get_rect(center=pill.center))
            y = pill.bottom + 14

        # the card: status with a spinner, then what to do
        cw = min(w - 40, 700)
        ch = 64 + (len(details) * 26 + 12 if details else 0)
        card = pygame.Rect((w - cw) // 2, y, cw, ch)
        theme.panel(screen, card)
        sx, sy = card.x + 44, card.y + 22
        for k in range(8):
            a = now * 2 * math.pi * 0.8 + k * math.pi / 4
            fade = (k + 1) / 8
            pygame.draw.circle(screen, theme.mix(t.surface, t.status, fade),
                               (int(card.x + 26 + 9 * math.cos(a)), int(sy + 11 + 9 * math.sin(a))), 2)
        img = self.font_status.render(status, True, t.status)
        screen.blit(img, (sx, sy))
        y = sy + 42
        if details:
            pygame.draw.line(screen, t.border, (card.x + 20, y - 8), (card.right - 20, y - 8))
        for line in details:
            img = self.font.render(line, True, t.text2)
            screen.blit(img, (card.x + 24, y + 4))
            y += 26

        hint = self.font_small.render("Ctrl+Alt — настройки: режим, качество, звук, оформление",
                                      True, t.muted)
        hy = max(card.bottom + 16, h - 30)
        screen.blit(hint, hint.get_rect(midtop=(w // 2, hy)))
        if self.panel:
            self.panel.draw(screen)
        pygame.display.flip()

    def _set_status(self, status, details=()):
        with self._lock:
            self.status, self.details = status, list(details)

    # ----- connecting (background thread) --------------------------------

    def _connect_loop(self):
        root_tried = 0.0
        while not self._stop:
            try:
                adb = Adb(self.serial)
                devices = adb.devices()
                ready = [d for d in devices if d[1] == "device"]
                if not ready:
                    if any(d[1] == "unauthorized" for d in devices):
                        self._set_status("Подтвердите отладку на телефоне", [
                            "Разблокируйте телефон: там должен быть запрос",
                            "«Разрешить отладку по USB?» — отметьте «Всегда» и нажмите «Разрешить».",
                            "Если запроса нет — выньте и снова вставьте кабель."])
                    else:
                        # No access to the USB device is the usual cause on
                        # Chromebooks: retry with an adb server started as root.
                        if time.monotonic() - root_tried > 20:
                            root_tried = time.monotonic()
                            self._set_status("Ищу телефон")
                            if adb.restart_server_as_root():
                                continue
                        self._set_status("Телефон не найден", CHECKLIST)
                    time.sleep(1.5)
                    continue

                adb.select_device(pick_first=True)
                name = next((d[2].replace("model:", "").split()[0] for d in ready
                             if d[0] == adb.serial and "model:" in d[2]), adb.serial)
                self._set_status("Подключаюсь к %s" % name.replace("_", " "))
                max_size, bit_rate, max_fps = settings_mod.video_params(self.options, self.screen_long)
                session = Session(adb, max_size=max_size, bit_rate=parse_bit_rate(bit_rate),
                                  max_fps=max_fps, audio=self.options["audio"],
                                  server_file=self.server_file, stay_awake=self.stay_awake,
                                  verbose=self.verbose)
                try:
                    session.start()
                except BaseException:
                    session.close()
                    raise
                if self._stop:
                    session.close()
                    return
                with self._lock:
                    self._result = (session, adb)
                return
            except AdbError as e:
                print("phonecast: %s" % e, file=sys.stderr)
                self._set_status("Проблема с adb", str(e).splitlines())
            except (SessionError, OSError, EOFError) as e:
                print("phonecast: %s" % e, file=sys.stderr)
                self._set_status("Не удалось запустить трансляцию, пробую снова",
                                 str(e).splitlines()[:6])
            time.sleep(2)

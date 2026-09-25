"""The application window around mirroring sessions.

Waits for the phone with friendly instructions, starts a session, returns to
waiting (and reconnects) when the cable is pulled, until the window is closed.
"""

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
        self.font = _font(16)
        self.font_title = _font(28, bold=True)
        self.font_status = _font(19, bold=True)
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

    # ----- waiting screen ------------------------------------------------

    def _wait_for_phone(self):
        # Keep the current window (after a lost connection) instead of
        # closing and reopening a small one.
        screen = pygame.display.get_surface()
        if screen is None:
            screen = pygame.display.set_mode((760, 460), pygame.RESIZABLE)
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
                    self.panel = SettingsPanel(self.options, self.font, self.font_status)
            with self._lock:
                result = self._result
            if result:
                self.message = ""
                return result
            self._draw(screen)
            clock.tick(15)

    def _draw(self, screen):
        screen.fill((24, 26, 32))
        w = screen.get_width()
        y = 36
        title = self.font_title.render("Phonecast", True, (240, 240, 245))
        screen.blit(title, title.get_rect(midtop=(w // 2, y)))
        y += 58
        hint = self.font.render("Ctrl+Alt — настройки (режим, качество, звук, подсказки)",
                                True, (150, 150, 165))
        screen.blit(hint, hint.get_rect(midtop=(w // 2, y)))
        y += 44
        if self.message:
            img = self.font.render(self.message, True, (255, 200, 120))
            screen.blit(img, img.get_rect(midtop=(w // 2, y)))
            y += 32
        dots = "." * (int(time.monotonic() * 2) % 4)
        with self._lock:
            status, details = self.status, list(self.details)
        img = self.font_status.render(status + dots, True, (130, 200, 255))
        screen.blit(img, img.get_rect(midtop=(w // 2, y)))
        y += 48
        for line in details:
            img = self.font.render(line, True, (215, 215, 222))
            screen.blit(img, (max(20, w // 2 - 330), y))
            y += 26
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

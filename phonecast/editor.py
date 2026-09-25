"""In-window editor for key mapping profiles (F3)."""

import math
import os

import pygame

from . import keys
from .keymap import mapping_keys

HANDLE_RADIUS = 24

EDITOR_HELP = [
    "РЕДАКТОР РАСКЛАДКИ  (F3 или Esc — сохранить и выйти)",
    "Клик по пустому месту → нажмите клавишу или кнопку мыши: кнопка-касание",
    "J — джойстик WASD под курсором     M — зона прицела (обзор мышью) под курсором",
    "K под кнопкой атаки → клавиша/кнопка мыши: атака с прицелом в сторону курсора",
    "Перетаскивание — переместить     ПКМ / Delete — удалить элемент под курсором",
    "Колесо над джойстиком/прицелом — размер     [ ] — чувствительность прицела",
    "N — новый профиль для текущего приложения     P — привязать профиль к приложению",
    "H — скрыть / показать эту подсказку",
]


def _r(v):
    return round(v, 4)


class Editor:
    def __init__(self, app):
        self.app = app
        self.profile = app.profile
        self.pending = None      # normalized point waiting for a key
        self.pending_type = "tap"
        self.drag = None         # (mapping index, last normalized pos)
        self.dirty = False
        self.show_help = True

    # ----- helpers -------------------------------------------------------

    def _handle_pos(self, m):
        if m["type"] == "swipe":
            return self.app.norm_to_window(*m["from"])
        return self.app.norm_to_window(m["x"], m["y"])

    def hit(self, pos):
        best, best_d = None, HANDLE_RADIUS
        for i, m in enumerate(self.profile.mappings):
            if m["type"] == "android":
                continue
            hx, hy = self._handle_pos(m)
            d = math.hypot(pos[0] - hx, pos[1] - hy)
            if d <= best_d:
                best, best_d = i, d
        return best

    def _changed(self):
        self.dirty = True
        self.app.engine.reload()

    def _norm_mouse(self):
        pos = pygame.mouse.get_pos()
        if not self.app.inside_view(pos):
            return None
        nx, ny = self.app.window_to_norm(pos)
        return _r(nx), _r(ny)

    def _find_type(self, t):
        for i, m in enumerate(self.profile.mappings):
            if m["type"] == t:
                return i
        return None

    def _bind_tap(self, key):
        # A key may drive only one thing: replace simple bindings using it,
        # refuse if it is part of a joystick or the aim toggle.
        for m in self.profile.mappings:
            if m["type"] in ("joystick", "aim") and key in mapping_keys(m):
                self.app.toast("%s уже используется (%s)" % (keys.pretty(key),
                               "джойстик" if m["type"] == "joystick" else "прицел"))
                return
        self.profile.mappings = [m for m in self.profile.mappings
                                 if not (m["type"] in ("tap", "swipe", "android", "skill")
                                         and m["key"] == key)]
        x, y = self.pending
        if self.pending_type == "skill":
            self.profile.mappings.append({"type": "skill", "key": key, "x": x, "y": y,
                                          "radius": 0.1, "origin": [0.5, 0.5], "range": 0.35})
            self.app.toast("Атака с прицелом на %s назначена" % keys.pretty(key))
        else:
            self.profile.mappings.append({"type": "tap", "key": key, "x": x, "y": y})
            self.app.toast("Кнопка %s назначена" % keys.pretty(key))
        self._changed()

    # ----- events --------------------------------------------------------

    def handle_event(self, ev):
        if self.pending is not None:
            return self._handle_pending(ev)

        if ev.type == pygame.KEYDOWN:
            name = keys.key_name(ev.scancode, pygame.key.name(ev.key))
            self._key(name, ev)
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            idx = self.hit(ev.pos)
            if ev.button == 1:
                if idx is not None:
                    self.drag = (idx, self.app.window_to_norm(ev.pos))
                elif self.app.inside_view(ev.pos):
                    nx, ny = self.app.window_to_norm(ev.pos)
                    self.pending = (_r(nx), _r(ny))
                    self.pending_type = "tap"
                    self.app.toast("Нажмите клавишу или кнопку мыши для этой точки (Esc — отмена)", 60)
            elif ev.button == 3 and idx is not None:
                self._delete(idx)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            if self.drag:
                self.drag = None
                self._changed()
        elif ev.type == pygame.MOUSEMOTION and self.drag:
            idx, (lx, ly) = self.drag
            nx, ny = self.app.window_to_norm(ev.pos)
            nx, ny = min(max(nx, 0.0), 1.0), min(max(ny, 0.0), 1.0)
            dx, dy = nx - lx, ny - ly
            m = self.profile.mappings[idx]
            if m["type"] == "swipe":
                m["from"] = [_r(m["from"][0] + dx), _r(m["from"][1] + dy)]
                m["to"] = [_r(m["to"][0] + dx), _r(m["to"][1] + dy)]
            else:
                m["x"], m["y"] = _r(nx), _r(ny)
            self.drag = (idx, (nx, ny))
            self.dirty = True
        elif ev.type == pygame.MOUSEWHEEL:
            idx = self.hit(pygame.mouse.get_pos())
            if idx is not None:
                m = self.profile.mappings[idx]
                if m["type"] in ("joystick", "aim", "skill"):
                    default = {"joystick": 0.12, "aim": 0.3, "skill": 0.1}[m["type"]]
                    r = float(m.get("radius", default)) + 0.01 * ev.y
                    m["radius"] = _r(min(max(r, 0.03), 0.6))
                    self._changed()
        return True

    def _handle_pending(self, ev):
        key = None
        if ev.type == pygame.KEYDOWN:
            key = keys.key_name(ev.scancode, pygame.key.name(ev.key))
            if key == "escape":
                self.pending = None
                self.app.toast("Отменено")
                return True
            if key in keys.RESERVED:
                self.app.toast("F1–F12 зарезервированы программой")
                return True
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            key = keys.MOUSE_BUTTON_NAMES.get(ev.button)
        if key:
            self._bind_tap(key)
            self.pending = None
            self.app.toasts = [t for t in self.app.toasts if not t[0].startswith("Нажмите клавишу")]
        return True

    def _key(self, name, ev):
        maps = self.profile.mappings
        if name == "escape":
            self.app.toggle_editor()
        elif name == "j":
            pos = self._norm_mouse()
            if pos:
                i = self._find_type("joystick")
                if i is None:
                    maps.append({"type": "joystick", "x": pos[0], "y": pos[1], "radius": 0.12,
                                 "up": "w", "left": "a", "down": "s", "right": "d", "walk": "lshift"})
                    self.app.toast("Джойстик WASD добавлен (Shift — шаг)")
                else:
                    maps[i]["x"], maps[i]["y"] = pos
                self._changed()
        elif name == "k":
            pos = self._norm_mouse()
            if pos:
                self.pending, self.pending_type = pos, "skill"
                self.app.toast("Нажмите клавишу или кнопку мыши для атаки с прицелом (Esc — отмена)", 60)
        elif name == "m":
            pos = self._norm_mouse()
            if pos:
                i = self._find_type("aim")
                if i is None:
                    maps.append({"type": "aim", "toggle": "`", "x": pos[0], "y": pos[1],
                                 "radius": 0.3, "sensitivity": 1.0})
                    self.app.toast("Прицел добавлен. Клавиша ` (под Esc) включает обзор мышью")
                else:
                    maps[i]["x"], maps[i]["y"] = pos
                self._changed()
        elif name == "h":
            self.show_help = not self.show_help
        elif name in ("[", "]"):
            i = self._find_type("aim")
            if i is not None:
                s = float(maps[i].get("sensitivity", 1.0)) * (1.1 if name == "]" else 1 / 1.1)
                maps[i]["sensitivity"] = round(min(max(s, 0.1), 10.0), 2)
                self.app.toast("Чувствительность прицела: %.2f" % maps[i]["sensitivity"])
                self._changed()
        elif name in ("delete", "backspace"):
            idx = self.hit(pygame.mouse.get_pos())
            if idx is not None:
                self._delete(idx)
        elif name == "n":
            self.save()
            pkg = self.app.fg_package
            self.app.add_profile(pkg or "Profile %d" % (len(self.app.profiles) + 1), pkg)
            self.profile = self.app.profile
            self.app.toast("Новый профиль «%s»" % self.profile.name
                           + (" — включится сам в этом приложении" if pkg else ""), 4)
        elif name == "p":
            pkg = self.app.fg_package
            if not pkg:
                self.app.toast("Не удалось определить текущее приложение")
            elif pkg in self.profile.packages:
                self.profile.packages.remove(pkg)
                self.dirty = True
                self.app.toast("Профиль отвязан от %s" % pkg)
            else:
                self.profile.packages.append(pkg)
                self.dirty = True
                self.app.toast("Профиль будет включаться в %s" % pkg)

    def _delete(self, idx):
        m = self.profile.mappings.pop(idx)
        self.app.toast("Удалено: %s" % (m.get("key") or m["type"]))
        self._changed()

    # ----- lifecycle -----------------------------------------------------

    def save(self):
        if self.dirty or not (self.profile.path and os.path.exists(self.profile.path)):
            self.profile.save()
            self.dirty = False

    def close(self):
        self.save()
        self.app.engine.reload()

    # ----- drawing -------------------------------------------------------

    def draw(self, surface):
        shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 30, 90))
        surface.blit(shade, (0, 0))
        hover = self.hit(pygame.mouse.get_pos())
        self.app.draw_mappings(surface, alpha=230, selected=hover)
        if self.pending:
            c = self.app.norm_to_window(*self.pending)
            pygame.draw.circle(surface, (255, 80, 80), c, 20, 3)
            self.app.label(surface, "?", c, color=(255, 120, 120))

        font = self.app.font
        head = EDITOR_HELP if self.show_help else [EDITOR_HELP[0] + "   H — подсказка"]
        lines = head + ["Профиль: %s%s" % (
            self.profile.name,
            ("   · авто: " + ", ".join(self.profile.packages)) if self.profile.packages else "")]
        if self.app.fg_package:
            lines.append("Текущее приложение: %s" % self.app.fg_package)
        w = max(font.size(line)[0] for line in lines) + 24
        h = len(lines) * 21 + 14
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(box, (0, 0, 0, 200), box.get_rect(), border_radius=8)
        for i, line in enumerate(lines):
            color = (255, 220, 90) if i == 0 else (230, 230, 230)
            box.blit(font.render(line, True, color), (12, 7 + i * 21))
        surface.blit(box, (8, 8))


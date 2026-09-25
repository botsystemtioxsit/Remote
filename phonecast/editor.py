"""Controls editor (F3 or the "Настроить управление" button), BlueStacks style.

A panel next to the phone picture holds the control types; they are dragged
onto the screen. Clicking a key label on the screen reassigns that key,
elements are moved by dragging, resized with the wheel or the panel buttons,
deleted with the right button. "Сохранить" writes the profile, "Отмена"
restores it as it was when the editor was opened.
"""

import copy
import math
import os

import pygame

from . import keys

PANEL_W = 270
HANDLE_RADIUS = 24

PALETTE = [
    ("tap", "Кнопка (нажатие)"),
    ("skill", "Атака с прицелом"),
    ("joystick", "Джойстик WASD"),
    ("aim", "Обзор мышью (FPS)"),
    ("swipe", "Свайп"),
]

TYPE_NAMES = {
    "tap": "Кнопка", "skill": "Атака с прицелом", "joystick": "Джойстик",
    "aim": "Обзор мышью", "swipe": "Свайп", "android": "Системная кнопка",
}

DEFAULT_RADIUS = {"joystick": 0.12, "aim": 0.3, "skill": 0.1}

# Keys that cannot be assigned: F1-F12 belong to the program, left Alt
# switches between battle and menu.
FORBIDDEN = keys.RESERVED | {"lalt"}


def _r(v):
    return round(v, 4)


def key_roles(m):
    """[(role, key)] of a mapping, in display order."""
    t = m["type"]
    if t == "joystick":
        return [(d, m[d]) for d in ("up", "left", "down", "right", "walk") if m.get(d)]
    if t == "aim":
        return [("toggle", m["toggle"])]
    return [("key", m["key"])]


class Editor:
    def __init__(self, app):
        self.app = app
        self.profile = app.profile
        self._snapshot = (copy.deepcopy(self.profile.mappings), list(self.profile.packages))
        self.selected = None     # index of the selected mapping
        self.capture = None      # waiting for a key: {"idx", "role"} or {"new": mapping}
        self.drag = None         # {"kind": "move"|"swipe_end"|"palette", ...}
        self.dirty = False
        self._labels = []        # [(rect, idx, role)] drawn this frame
        self._buttons = []       # [(rect, action, caption)] of the panel

    # ----- geometry ------------------------------------------------------

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

    def _hit_swipe_end(self, pos):
        for i, m in enumerate(self.profile.mappings):
            if m["type"] == "swipe":
                ex, ey = self.app.norm_to_window(*m["to"])
                if math.hypot(pos[0] - ex, pos[1] - ey) <= 14:
                    return i
        return None

    def _norm(self, pos):
        nx, ny = self.app.window_to_norm(pos)
        return _r(min(max(nx, 0.0), 1.0)), _r(min(max(ny, 0.0), 1.0))

    def _changed(self):
        self.dirty = True
        self.app.engine.reload()
        self.app.dirty = True

    # ----- key assignment ------------------------------------------------

    def _holder(self, key):
        for j, m in enumerate(self.profile.mappings):
            for role, k in key_roles(m):
                if k == key:
                    return j, role
        return None

    def assign(self, key):
        """Give `key` to the element being captured. Returns True when done."""
        if key in FORBIDDEN:
            self.app.toast("F1–F12 заняты программой, левый Alt переключает бой/меню", 4)
            return False
        cap = self.capture
        maps = self.profile.mappings
        holder = self._holder(key)
        if "new" in cap:
            new = cap["new"]
            if holder:
                j, role = holder
                if role != "key":
                    self.app.toast("%s уже в %s — сначала смените её там"
                                   % (keys.pretty(key), TYPE_NAMES[maps[j]["type"]].lower()), 4)
                    return False
                maps.pop(j)
                self.app.toast("%s перенесена на новый элемент" % keys.pretty(key))
            new["toggle" if new["type"] == "aim" else "key"] = key
            maps.append(new)
            self.selected = len(maps) - 1
        else:
            idx, role = cap["idx"], cap["role"]
            m = maps[idx]
            old = m.get(role)
            if holder == (idx, role):
                return True
            m[role] = key
            if holder:
                j, hrole = holder
                if old:
                    maps[j][hrole] = old
                    self.app.toast("%s и %s поменялись местами" % (keys.pretty(key), keys.pretty(old)), 4)
                elif hrole in ("key", "toggle", "up", "left", "down", "right"):
                    m[role] = old  # cannot leave the other element without a key
                    self.app.toast("%s уже занята" % keys.pretty(key))
                    return False
                else:
                    maps[j].pop(hrole, None)
        self._changed()
        return True

    def start_capture(self, idx=None, role=None, new=None):
        self.capture = {"new": new} if new is not None else {"idx": idx, "role": role}
        self.app.toast("Нажмите клавишу или кнопку мыши (Esc — отмена)", 60)

    def _end_capture(self):
        self.capture = None
        self.app.toasts = [t for t in self.app.toasts if not t[0].startswith("Нажмите клавишу")]

    # ----- creating elements ---------------------------------------------

    def _create(self, kind, pos):
        maps = self.profile.mappings
        x, y = pos
        if kind == "tap":
            self.start_capture(new={"type": "tap", "key": None, "x": x, "y": y})
        elif kind == "skill":
            self.start_capture(new={"type": "skill", "key": None, "x": x, "y": y, "radius": 0.1,
                                    "origin": [0.5, 0.5], "range": 0.35})
        elif kind == "swipe":
            self.start_capture(new={"type": "swipe", "key": None, "from": [x, y],
                                    "to": [x, _r(max(0.0, y - 0.25))], "duration": 150})
        elif kind == "joystick":
            used = {k for m in maps for _r_, k in key_roles(m)}
            if {"w", "a", "s", "d"} & used:
                self.app.toast("WASD уже заняты — удалите или смените те кнопки", 4)
                return
            maps.append({"type": "joystick", "x": x, "y": y, "radius": 0.12,
                         "up": "w", "left": "a", "down": "s", "right": "d"})
            self.selected = len(maps) - 1
            self.app.toast("Джойстик WASD добавлен. Клик по букве — сменить клавишу")
            self._changed()
        elif kind == "aim":
            if any(m["type"] == "aim" for m in maps):
                self.app.toast("Обзор мышью уже есть — перетащите его")
                return
            toggle = "`" if not self._holder("`") else None
            m = {"type": "aim", "toggle": toggle, "x": x, "y": y, "radius": 0.3,
                 "sensitivity": 1.0, "auto": True}
            if toggle is None:
                self.start_capture(new=m)
                return
            maps.append(m)
            self.selected = len(maps) - 1
            self.app.toast("Обзор мышью добавлен: включается сам в бою, ` — отпустить мышь", 5)
            self._changed()

    # ----- events --------------------------------------------------------

    def handle_event(self, ev):
        if self.capture is not None:
            return self._handle_capture(ev)
        if ev.type == pygame.KEYDOWN:
            name = keys.key_name(ev.scancode, pygame.key.name(ev.key))
            if name == "escape":
                self.app.toggle_editor(save=True)
            elif name in ("delete", "backspace") and self.selected is not None:
                self._delete(self.selected)
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            self._mouse_down(ev)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self._mouse_up(ev)
        elif ev.type == pygame.MOUSEMOTION and self.drag:
            self._drag_to(ev.pos)
        elif ev.type == pygame.MOUSEWHEEL:
            idx = self.hit(pygame.mouse.get_pos())
            if idx is not None:
                self._resize(idx, ev.y)
        return True

    def _handle_capture(self, ev):
        key = None
        if ev.type == pygame.KEYDOWN:
            key = keys.key_name(ev.scancode, pygame.key.name(ev.key))
            if key == "escape":
                self._end_capture()
                self.app.toast("Отменено")
                return True
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button in keys.MOUSE_BUTTON_NAMES:
            key = keys.MOUSE_BUTTON_NAMES[ev.button]
        if key and self.assign(key):
            self._end_capture()
        return True

    def _mouse_down(self, ev):
        for rect, action, _caption in self._buttons:
            if rect.collidepoint(ev.pos):
                if ev.button == 1:
                    action()
                return
        if ev.pos[0] >= self._panel_x():
            return
        if ev.button == 1:
            for rect, idx, role in self._labels:
                if rect.collidepoint(ev.pos) and role:
                    self.selected = idx
                    self.start_capture(idx=idx, role=role)
                    return
            end = self._hit_swipe_end(ev.pos)
            if end is not None:
                self.selected = end
                self.drag = {"kind": "swipe_end", "idx": end}
                return
            idx = self.hit(ev.pos)
            if idx is not None:
                self.selected = idx
                self.drag = {"kind": "move", "idx": idx, "last": self._norm(ev.pos)}
            else:
                self.selected = None
        elif ev.button == 3:
            idx = self.hit(ev.pos)
            if idx is not None:
                self._delete(idx)

    def _mouse_up(self, ev):
        drag, self.drag = self.drag, None
        if not drag:
            return
        if drag["kind"] == "palette":
            if self.app.inside_view(ev.pos) and ev.pos[0] < self._panel_x():
                self._create(drag["type"], self._norm(ev.pos))
        else:
            self._changed()

    def _drag_to(self, pos):
        d = self.drag
        if d["kind"] == "palette":
            d["pos"] = pos
            return
        m = self.profile.mappings[d["idx"]]
        nx, ny = self._norm(pos)
        if d["kind"] == "swipe_end":
            m["to"] = [nx, ny]
        elif m["type"] == "swipe":
            lx, ly = d["last"]
            m["from"] = [_r(m["from"][0] + nx - lx), _r(m["from"][1] + ny - ly)]
            m["to"] = [_r(m["to"][0] + nx - lx), _r(m["to"][1] + ny - ly)]
            d["last"] = (nx, ny)
        else:
            m["x"], m["y"] = nx, ny
        self.dirty = True

    def _resize(self, idx, direction):
        m = self.profile.mappings[idx]
        if m["type"] in DEFAULT_RADIUS:
            r = float(m.get("radius", DEFAULT_RADIUS[m["type"]])) + 0.01 * direction
            m["radius"] = _r(min(max(r, 0.03), 0.6))
            self._changed()

    def _sensitivity(self, idx, factor):
        m = self.profile.mappings[idx]
        m["sensitivity"] = round(min(max(float(m.get("sensitivity", 1.0)) * factor, 0.1), 10.0), 2)
        self._changed()

    def _toggle(self, idx, field):
        m = self.profile.mappings[idx]
        m[field] = not m.get(field, False)
        self._changed()

    def _delete(self, idx):
        m = self.profile.mappings.pop(idx)
        self.selected = None
        self.app.toast("Удалено: %s" % TYPE_NAMES.get(m["type"], m["type"]))
        self._changed()

    def _toggle_package(self):
        pkg = self.app.fg_package
        if not pkg:
            self.app.toast("Не удалось определить текущее приложение")
        elif pkg in self.profile.packages:
            self.profile.packages.remove(pkg)
            self.dirty = True
        else:
            self.profile.packages.append(pkg)
            self.dirty = True

    def _new_profile(self):
        self.close(save=True)
        pkg = self.app.fg_package
        self.app.add_profile(pkg or "Профиль %d" % (len(self.app.profiles) + 1), pkg)
        self.__init__(self.app)
        self.dirty = True
        self.app.toast("Новый пустой профиль «%s»" % self.profile.name, 4)

    # ----- lifecycle -----------------------------------------------------

    def save(self):
        if self.dirty or not (self.profile.path and os.path.exists(self.profile.path)):
            self.profile.save()
            self.dirty = False

    def close(self, save=True):
        if save:
            self.save()
        else:
            self.profile.mappings, self.profile.packages = self._snapshot
        self.app.engine.reload()

    # ----- drawing -------------------------------------------------------

    def _panel_x(self):
        return self.app.screen.get_width() - PANEL_W

    def draw(self, surface):
        shade = pygame.Surface(self.app.view.size, pygame.SRCALPHA)
        shade.fill((0, 0, 30, 70))
        surface.blit(shade, self.app.view.topleft)
        hover = self.hit(pygame.mouse.get_pos())
        self.app.draw_mappings(surface, alpha=230, selected=self.selected if hover is None else hover,
                               labels=False, areas=True)
        self._draw_labels(surface)
        if self.drag and self.drag["kind"] == "palette" and "pos" in self.drag:
            pygame.draw.circle(surface, (255, 210, 0), self.drag["pos"], 22, 3)
        self._draw_panel(surface)

    def _draw_labels(self, surface):
        self._labels = []
        cap = self.capture or {}
        fh = self.app.view.h
        taken = {}
        maps = list(self.profile.mappings)
        if "new" in cap:
            maps.append(cap["new"])
        for i, m in enumerate(maps):
            t = m["type"]
            spots = []
            if t in ("tap", "skill"):
                spots = [("key", self.app.norm_to_window(m["x"], m["y"]))]
            elif t == "swipe":
                spots = [("key", self.app.norm_to_window(*m["from"]))]
            elif t == "joystick":
                cx, cy = self.app.norm_to_window(m["x"], m["y"])
                r = int(float(m.get("radius", 0.12)) * fh)
                for d, (ox, oy) in (("up", (0, -1)), ("down", (0, 1)), ("left", (-1, 0)), ("right", (1, 0))):
                    spots.append((d, (cx + ox * r, cy + oy * r)))
            elif t == "aim":
                cx, cy = self.app.norm_to_window(m["x"], m["y"])
                spots = [("toggle", (cx, cy + 32))]
            for role, pos in spots:
                n = taken.get(pos, 0)
                taken[pos] = n + 1
                pos = (pos[0], pos[1] + n * 24)  # keys on the same point: stacked
                waiting = (cap.get("new") is m) or (cap.get("idx") == i and cap.get("role") == role)
                key = m.get(role)
                text = "?" if waiting or not key else keys.pretty(key)
                if t == "skill" and not waiting:
                    text += " →"
                if t == "aim" and not waiting:
                    text = "обзор: " + text
                color = (255, 110, 110) if waiting else (255, 255, 255)
                bg = (90, 0, 0, 220) if waiting else ((120, 90, 0, 220) if i == self.selected
                                                      else (0, 0, 0, 190))
                rect = self.app.label(surface, text, pos, color=color, bg=bg)
                if i < len(self.profile.mappings):
                    self._labels.append((rect, i, role))

    def _button(self, surface, rect, text, action, primary=False, active=True):
        mouse = pygame.mouse.get_pos()
        base = (40, 110, 200) if primary else (55, 60, 72)
        if not active:
            base = (40, 42, 50)
        elif rect.collidepoint(mouse):
            base = tuple(min(255, c + 25) for c in base)
        pygame.draw.rect(surface, base, rect, border_radius=7)
        img = self.app.font.render(text, True, (240, 240, 245) if active else (130, 130, 140))
        surface.blit(img, img.get_rect(center=rect.center))
        if active:
            self._buttons.append((rect, action, text))

    def _draw_panel(self, surface):
        self._buttons = []
        x0 = self._panel_x()
        h = surface.get_height()
        pygame.draw.rect(surface, (28, 30, 38), (x0, 0, PANEL_W, h))
        font, small = self.app.font, self.app.font_small
        x, w = x0 + 14, PANEL_W - 28
        y = 12

        def text(t, color=(225, 225, 232), f=None):
            nonlocal y
            img = (f or font).render(t, True, color)
            surface.blit(img, (x, y))
            y += img.get_height() + 4

        text("Настройка управления", (255, 220, 90), self.app.font_big)
        text(self.profile.name[:28], (170, 200, 255), small)
        y += 6
        text("Перетащите на экран:", (170, 170, 180), small)
        for kind, name in PALETTE:
            self._button(surface, pygame.Rect(x, y, w, 27), name, lambda k=kind: self._start_palette(k))
            y += 31
        y += 6

        def stepper(caption, minus, plus):
            # "caption   [−] [+]" on one row
            nonlocal y
            img = small.render(caption, True, (225, 225, 232))
            surface.blit(img, (x, y + 6))
            bw = 40
            self._button(surface, pygame.Rect(x + w - 2 * bw - 6, y, bw, 26), "−", minus)
            self._button(surface, pygame.Rect(x + w - bw, y, bw, 26), "+", plus)
            y += 31

        sel = self.selected
        if sel is not None and sel < len(self.profile.mappings):
            m = self.profile.mappings[sel]
            t = m["type"]
            text("Выбрано: " + TYPE_NAMES.get(t, t), (255, 220, 90))
            if t == "joystick":
                text("Клик по букве на экране — сменить", (170, 170, 180), small)
            else:
                role = key_roles(m)[0][0]
                self._button(surface, pygame.Rect(x, y, w, 26),
                             "Клавиша: %s — сменить" % keys.pretty(m.get(role) or "?"),
                             lambda i=sel, r=role: self.start_capture(idx=i, role=r))
                y += 31
            if t in DEFAULT_RADIUS:
                stepper("Размер: %d%%" % round(float(m.get("radius", DEFAULT_RADIUS[t])) * 100),
                        lambda i=sel: self._resize(i, -1), lambda i=sel: self._resize(i, 1))
            if t == "aim":
                stepper("Чувствит.: %.2f" % float(m.get("sensitivity", 1.0)),
                        lambda i=sel: self._sensitivity(i, 1 / 1.15),
                        lambda i=sel: self._sensitivity(i, 1.15))
                self._button(surface, pygame.Rect(x, y, w, 26),
                             "Захват мыши в бою: %s" % ("да" if m.get("auto") else "нет"),
                             lambda i=sel: self._toggle(i, "auto"))
                y += 31
            self._button(surface, pygame.Rect(x, y, w, 26), "Удалить", lambda i=sel: self._delete(i))
            y += 31
        else:
            for line in ("Клик по элементу — выбрать", "Клик по подписи — сменить клавишу",
                         "Перетаскивание — переместить", "Колесо — размер, ПКМ — удалить"):
                text(line, (170, 170, 180), small)

        # Bottom: profile buttons above Save / Cancel, dropped if there is no room.
        by = h - 46
        half = (w - 8) // 2
        self._button(surface, pygame.Rect(x, by, half, 34), "Сохранить",
                     lambda: self.app.toggle_editor(save=True), primary=True)
        self._button(surface, pygame.Rect(x + half + 8, by, half, 34), "Отмена",
                     lambda: self.app.toggle_editor(save=False))
        pkg = self.app.fg_package
        rows = [("Новый профиль для этой игры", self._new_profile)]
        if pkg:
            on = pkg in self.profile.packages
            rows.insert(0, ("Включать в этой игре: %s" % ("да" if on else "нет"), self._toggle_package))
        py = by - 8 - 31 * len(rows)
        if py >= y + 4:
            for label, action in rows:
                self._button(surface, pygame.Rect(x, py, w, 26), label, action)
                py += 31

    def _start_palette(self, kind):
        self.drag = {"kind": "palette", "type": kind}
        self.app.toast("Отпустите над нужной кнопкой игры", 3)

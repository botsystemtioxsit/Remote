"""Settings panel (Ctrl+Alt), shared by the waiting screen and the stream window."""

import pygame

from . import settings as settings_mod
from . import theme

SENSITIVITY_STEPS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.5, 3.0]


class Stepper:
    """A "−  value  +" row instead of choice buttons."""

    def __init__(self, steps, fmt="%.1f"):
        self.steps = steps
        self.fmt = fmt

    def step(self, value, direction):
        # nearest step, then one step up or down
        i = min(range(len(self.steps)), key=lambda k: abs(self.steps[k] - float(value)))
        return self.steps[max(0, min(len(self.steps) - 1, i + direction))]


class Cycle:
    """A "‹  name  ›" row for a long list of choices."""

    def __init__(self, choices):
        self.choices = choices   # [(value, text)]

    def step(self, value, direction):
        values = [v for v, _ in self.choices]
        i = values.index(value) if value in values else 0
        return values[(i + direction) % len(values)]

    def text(self, value):
        return dict(self.choices).get(value, str(value))


# (settings key, caption, [(value, text), ...] or Stepper or Cycle)
ROWS = [
    ("mode", "Режим", [("watch", "Только трансляция"), ("control", "Трансляция + управление")]),
    ("quality", "Качество", [(q, settings_mod.PRESET_NAMES[q]) for q in settings_mod.PRESET_ORDER]),
    ("audio", "Звук с телефона", [(True, "Вкл"), (False, "Выкл")]),
    ("mouse_sensitivity", "Мышь в играх", Stepper(SENSITIVITY_STEPS)),
    ("show_hints", "Подсказки кнопок", [(False, "Скрыты"), (True, "Показаны")]),
    ("fullscreen", "Полный экран", [(False, "Нет"), (True, "Да")]),
    ("screen_off", "Гасить экран телефона", [(False, "Нет"), (True, "Да")]),
    ("theme", "Оформление", Cycle([(t.key, t.name) for t in theme.THEMES])),
]

# Changing these needs a new connection to the phone.
RECONNECT_KEYS = ("quality", "audio")


def is_chord(ev):
    """Ctrl+Alt: the second of the two modifiers pressed."""
    if ev.type != pygame.KEYDOWN or ev.key not in (pygame.K_LCTRL, pygame.K_RCTRL,
                                                   pygame.K_LALT, pygame.K_RALT):
        return False
    mods = ev.mod
    return bool(mods & pygame.KMOD_CTRL) and bool(mods & pygame.KMOD_ALT)


class SettingsPanel:
    """Modal panel. `on_change(key, value)` is called for every choice; the
    value is also saved to settings.json right away."""

    def __init__(self, options, font, font_big, on_change=None):
        self.options = options
        self.font = font
        self.font_big = font_big
        self.on_change = on_change
        self.closed = False
        self._buttons = []   # [(rect, key, value)]
        self._close_rect = None
        self.changed = set()

    def choose(self, key, value):
        if self.options.get(key) == value:
            return
        self.options[key] = value
        if key == "theme":
            theme.apply(value)
        saved = settings_mod.load()
        saved[key] = value
        settings_mod.save(saved)
        self.changed.add(key)
        if self.on_change:
            self.on_change(key, value)

    @property
    def needs_reconnect(self):
        return any(k in self.changed for k in RECONNECT_KEYS)

    def handle_event(self, ev):
        """Returns True (the panel takes every event while it is open)."""
        if ev.type == pygame.KEYDOWN and (ev.key == pygame.K_ESCAPE or is_chord(ev)):
            self.closed = True
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._close_rect and self._close_rect.collidepoint(ev.pos):
                self.closed = True
            for rect, key, value in self._buttons:
                if rect.collidepoint(ev.pos):
                    if callable(value):
                        value = value()
                    self.choose(key, value)
        return True

    def draw(self, surface):
        self._buttons = []
        t = theme.T
        font, font_big = theme.font(15), theme.font(19, bold=True)
        sw, sh = surface.get_size()
        row_h, pad = 44, 24
        w = min(sw - 20, 760)
        h = min(sh - 20, pad * 2 + 52 + row_h * len(ROWS) + 56)
        box = pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h)
        shade = pygame.Surface((sw, sh), pygame.SRCALPHA)
        shade.fill(t.shade)
        surface.blit(shade, (0, 0))
        theme.panel(surface, box)

        x, y = box.x + pad, box.y + pad
        surface.blit(font_big.render(t.heading("Настройки"), True, t.text), (x, y))
        hint = font.render("Ctrl+Alt или Esc — закрыть", True, t.muted)
        surface.blit(hint, (box.right - pad - hint.get_width(), y + 4))
        y += 44
        pygame.draw.line(surface, t.border, (x, y - 8), (box.right - pad, y - 8))
        mouse = pygame.mouse.get_pos()
        # caption on the left, the choices on the right of the same row
        cx = x + min(230, (w - 2 * pad) * 2 // 5)
        cw = box.right - pad - cx
        for key, caption, choices in ROWS:
            img = font.render(caption, True, t.text2)
            surface.blit(img, (x, y + (34 - img.get_height()) // 2))
            if isinstance(choices, (Stepper, Cycle)):
                cur = self.options.get(key, 1.0 if isinstance(choices, Stepper) else theme.DEFAULT)
                bw = 44
                for i, (text, direction) in enumerate((("−", -1), ("+", 1)) if isinstance(choices, Stepper)
                                                      else (("‹", -1), ("›", 1))):
                    rect = pygame.Rect(cx if i == 0 else box.right - pad - bw, y, bw, 34)
                    theme.button(surface, rect, text, font_big, hover=rect.collidepoint(mouse))
                    # read the value at click time: two quick clicks between redraws count twice
                    self._buttons.append((rect, key, lambda d=direction, k=key, st=choices, c=cur:
                                          st.step(self.options.get(k, c), d)))
                inner = pygame.Rect(cx + bw + 12, y, cw - 2 * bw - 24, 34)
                if isinstance(choices, Stepper):
                    # a bar showing where the value is between the smallest and largest step
                    val = font_big.render(choices.fmt % float(cur), True, t.accent)
                    bar = pygame.Rect(inner.x, inner.centery - 3, inner.w - val.get_width() - 14, 6)
                    pygame.draw.rect(surface, t.control, bar, border_radius=3)
                    lo, hi = choices.steps[0], choices.steps[-1]
                    fill = bar.copy()
                    fill.w = max(6, int(bar.w * (float(cur) - lo) / (hi - lo)))
                    pygame.draw.rect(surface, t.accent, fill, border_radius=3)
                    pygame.draw.circle(surface, t.text, fill.midright, 7)
                    surface.blit(val, val.get_rect(midright=inner.midright))
                else:
                    val = font.render(choices.text(cur), True, t.text)
                    surface.blit(val, val.get_rect(center=inner.center))
                y += row_h
                continue
            bw = (cw - 6 * (len(choices) - 1)) // len(choices)
            bx = cx
            for value, text in choices:
                rect = pygame.Rect(bx, y, bw, 34)
                theme.button(surface, rect, text, font, chosen=self.options.get(key) == value,
                             hover=rect.collidepoint(mouse))
                self._buttons.append((rect, key, value))
                bx += bw + 6
            y += row_h
        self._close_rect = pygame.Rect(box.right - pad - 140, box.bottom - pad - 36, 140, 36)
        if self.needs_reconnect:
            note = "Качество и звук применятся после закрытия"
            img = font.render(note, True, t.warn)
            surface.blit(img, (x, self._close_rect.centery - img.get_height() // 2))
        theme.button(surface, self._close_rect, "Готово", font, primary=True,
                     hover=self._close_rect.collidepoint(mouse))

"""Settings panel (Ctrl+Alt), shared by the waiting screen and the stream window."""

import pygame

from . import settings as settings_mod

# (settings key, caption, [(value, text), ...])
ROWS = [
    ("mode", "Режим", [("watch", "Только трансляция"), ("control", "Трансляция + управление")]),
    ("quality", "Качество", [(q, settings_mod.PRESET_NAMES[q]) for q in settings_mod.PRESET_ORDER]),
    ("audio", "Звук с телефона", [(True, "Вкл"), (False, "Выкл")]),
    ("show_hints", "Подсказки кнопок в игре", [(False, "Скрыты"), (True, "Показаны")]),
    ("fullscreen", "Полный экран", [(False, "Нет"), (True, "Да")]),
    ("screen_off", "Гасить экран телефона", [(False, "Нет"), (True, "Да")]),
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
                    self.choose(key, value)
        return True

    def draw(self, surface):
        self._buttons = []
        sw, sh = surface.get_size()
        row_h, pad = 64, 22
        w = min(sw - 20, 720)
        h = min(sh - 20, pad * 2 + 46 + row_h * len(ROWS) + 58)
        box = pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h)
        shade = pygame.Surface((sw, sh), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        surface.blit(shade, (0, 0))
        pygame.draw.rect(surface, (30, 32, 40), box, border_radius=12)
        pygame.draw.rect(surface, (70, 76, 92), box, 1, border_radius=12)

        x, y = box.x + pad, box.y + pad
        surface.blit(self.font_big.render("Настройки", True, (245, 245, 250)), (x, y))
        hint = self.font.render("Ctrl+Alt или Esc — закрыть", True, (150, 150, 165))
        surface.blit(hint, (box.right - pad - hint.get_width(), y + 4))
        y += 46
        mouse = pygame.mouse.get_pos()
        for key, caption, choices in ROWS:
            surface.blit(self.font.render(caption, True, (200, 200, 212)), (x, y))
            by = y + 24
            bw = (w - 2 * pad - 8 * (len(choices) - 1)) // len(choices)
            bx = x
            for value, text in choices:
                rect = pygame.Rect(bx, by, bw, 32)
                chosen = self.options.get(key) == value
                color = (40, 110, 200) if chosen else ((70, 74, 88) if rect.collidepoint(mouse) else (48, 52, 64))
                pygame.draw.rect(surface, color, rect, border_radius=7)
                img = self.font.render(text, True, (240, 240, 245))
                surface.blit(img, img.get_rect(center=rect.center))
                self._buttons.append((rect, key, value))
                bx += bw + 8
            y += row_h
        note = "Качество и звук применятся после закрытия (переподключение за 1–2 с)" \
            if self.needs_reconnect else ""
        if note:
            surface.blit(self.font.render(note, True, (255, 210, 120)), (x, y + 4))
        self._close_rect = pygame.Rect(box.right - pad - 140, box.bottom - pad - 34, 140, 34)
        pygame.draw.rect(surface, (40, 110, 200), self._close_rect, border_radius=8)
        img = self.font.render("Готово", True, (245, 245, 250))
        surface.blit(img, img.get_rect(center=self._close_rect.center))

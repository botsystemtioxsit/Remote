"""Colour themes ("Оформление" in the settings panel).

Every window part draws with the colours of `T`, the current theme, so a
theme switch takes effect on the next frame. `apply(name)` changes it.
"""

import pygame

SANS = ("dejavusans", "notosans", "liberationsans", "freesans", "ubuntu")
MONO = ("dejavusansmono", "notosansmono", "liberationmono", "ubuntumono", "freemono")


class Theme:
    # defaults shared by most themes; each theme overrides what it needs
    fonts = SANS
    font_scale = 1.0         # monospace fonts are wider: drawn a bit smaller
    bg2 = None               # bottom colour of a vertical gradient (None: flat)
    radius = 8               # buttons
    radius_panel = 14        # panels and cards
    outline = False          # buttons drawn as outlines instead of filled
    upper = False            # headings in capitals
    glow = False             # soft glow around accent elements
    shade = (0, 0, 0, 150)   # dims the window under a modal panel
    letterbox = (0, 0, 0)    # around the phone picture

    def __init__(self, key, name, **colors):
        self.key, self.name = key, name
        for k, v in colors.items():
            setattr(self, k, v)
        # derived colours the themes rarely need to set
        if not hasattr(self, "control_hover"):
            self.control_hover = mix(self.control, self.text, 0.12)
        if not hasattr(self, "label_bg"):
            self.label_bg = self.surface + (215,)
        if not hasattr(self, "label_text"):
            self.label_text = self.text
        if not hasattr(self, "bar_bg"):
            self.bar_bg = self.control + (240,)

    def heading(self, text):
        return text.upper() if self.upper else text


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


THEMES = [
    Theme("graphite", "Графит",
          bg=(22, 24, 30), bg2=(30, 33, 42), surface=(32, 35, 44), border=(64, 70, 86),
          text=(240, 241, 246), text2=(196, 199, 212), muted=(140, 145, 162),
          accent=(56, 124, 230), on_accent=(255, 255, 255),
          control=(47, 51, 63), warn=(255, 196, 110), status=(126, 186, 255),
          hint=(0, 200, 255), sel=(255, 210, 0), danger=(230, 80, 80)),

    Theme("neon", "Неон",
          bg=(12, 8, 30), bg2=(34, 10, 52), surface=(24, 16, 48), border=(120, 60, 200),
          text=(246, 240, 255), text2=(206, 190, 240), muted=(150, 128, 196),
          accent=(255, 46, 160), on_accent=(255, 255, 255),
          control=(42, 28, 78), warn=(255, 220, 90), status=(0, 240, 255),
          hint=(0, 240, 255), sel=(255, 46, 160), danger=(255, 70, 90),
          glow=True, radius=10, radius_panel=16, shade=(8, 0, 24, 170), letterbox=(8, 4, 20)),

    Theme("nord", "Север",
          bg=(46, 52, 64), bg2=(59, 66, 82), surface=(59, 66, 82), border=(76, 86, 106),
          text=(236, 239, 244), text2=(216, 222, 233), muted=(160, 170, 190),
          accent=(136, 192, 208), on_accent=(46, 52, 64),
          control=(67, 76, 94), warn=(235, 203, 139), status=(143, 188, 187),
          hint=(136, 192, 208), sel=(235, 203, 139), danger=(191, 97, 106),
          radius=6, radius_panel=10, letterbox=(36, 41, 51)),

    Theme("dracula", "Вампир",
          bg=(40, 42, 54), bg2=(33, 34, 44), surface=(52, 55, 70), border=(98, 114, 164),
          text=(248, 248, 242), text2=(220, 220, 214), muted=(150, 160, 200),
          accent=(189, 147, 249), on_accent=(30, 30, 40),
          control=(68, 71, 90), warn=(241, 250, 140), status=(139, 233, 253),
          hint=(80, 250, 123), sel=(255, 121, 198), danger=(255, 85, 85),
          radius=12, radius_panel=18),

    Theme("terminal", "Терминал",
          bg=(6, 10, 6), surface=(8, 16, 8), border=(40, 180, 70),
          text=(120, 255, 140), text2=(90, 210, 110), muted=(50, 140, 70),
          accent=(60, 255, 100), on_accent=(4, 12, 4),
          control=(10, 26, 12), control_hover=(20, 56, 26), warn=(255, 200, 60), status=(120, 255, 140),
          hint=(60, 255, 100), sel=(255, 200, 60), danger=(255, 80, 60),
          label_bg=(0, 12, 0, 220),
          fonts=MONO, font_scale=0.88, radius=0, radius_panel=0, outline=True, upper=True, letterbox=(0, 0, 0)),

    Theme("ember", "Угли",
          bg=(28, 20, 18), bg2=(46, 26, 20), surface=(44, 32, 28), border=(110, 70, 50),
          text=(255, 240, 228), text2=(226, 200, 184), muted=(170, 136, 118),
          accent=(255, 112, 40), on_accent=(255, 255, 255),
          control=(64, 46, 40), warn=(255, 200, 90), status=(255, 170, 90),
          hint=(255, 140, 50), sel=(255, 230, 120), danger=(230, 60, 60),
          radius=10, radius_panel=16),

    Theme("paper", "Бумага",
          bg=(244, 245, 248), bg2=(228, 232, 240), surface=(255, 255, 255), border=(210, 214, 224),
          text=(28, 32, 44), text2=(66, 72, 90), muted=(120, 126, 142),
          accent=(64, 88, 230), on_accent=(255, 255, 255),
          control=(234, 237, 244), control_hover=(220, 225, 236), warn=(196, 110, 0),
          status=(64, 88, 230), hint=(0, 170, 255), sel=(255, 170, 0), danger=(220, 50, 60),
          label_bg=(255, 255, 255, 225), shade=(40, 44, 60, 110), letterbox=(20, 22, 28)),

    Theme("forest", "Лес",
          bg=(16, 28, 24), bg2=(22, 40, 32), surface=(26, 42, 36), border=(56, 96, 78),
          text=(232, 248, 238), text2=(190, 222, 204), muted=(128, 168, 148),
          accent=(64, 220, 150), on_accent=(10, 30, 22),
          control=(36, 58, 50), warn=(250, 210, 110), status=(120, 240, 190),
          hint=(64, 220, 150), sel=(250, 210, 110), danger=(235, 90, 90),
          radius=18, radius_panel=22),

    Theme("cyber", "Киберпанк",
          bg=(10, 10, 12), bg2=(18, 14, 22), surface=(20, 20, 24), border=(252, 238, 10),
          text=(250, 250, 240), text2=(210, 210, 200), muted=(140, 140, 130),
          accent=(252, 238, 10), on_accent=(10, 10, 12),
          control=(34, 34, 40), warn=(255, 0, 160), status=(0, 240, 255),
          hint=(252, 238, 10), sel=(255, 0, 160), danger=(255, 0, 80),
          fonts=MONO, font_scale=0.88, radius=0, radius_panel=0, upper=True, glow=True),

    Theme("latte", "Латте",
          bg=(239, 233, 222), bg2=(226, 214, 198), surface=(250, 246, 240), border=(210, 196, 178),
          text=(60, 44, 36), text2=(96, 76, 64), muted=(150, 128, 112),
          accent=(136, 57, 239), on_accent=(255, 255, 255),
          control=(234, 224, 210), control_hover=(222, 208, 190), warn=(200, 100, 20),
          status=(136, 57, 239), hint=(136, 57, 239), sel=(230, 120, 30), danger=(210, 60, 60),
          label_bg=(250, 246, 240, 230), shade=(60, 40, 30, 110), letterbox=(30, 24, 20),
          radius=16, radius_panel=20),
]

BY_KEY = {t.key: t for t in THEMES}
DEFAULT = "graphite"
T = BY_KEY[DEFAULT]

_fonts = {}
_gradients = {}


def apply(key):
    global T
    T = BY_KEY.get(key, BY_KEY[DEFAULT])
    return T


def font(size, bold=False):
    size = round(size * T.font_scale)
    k = (T.fonts, size, bold)
    if k not in _fonts:
        for name in T.fonts:
            path = pygame.font.match_font(name, bold=bold)
            if path:
                _fonts[k] = pygame.font.Font(path, size)
                break
        else:
            _fonts[k] = pygame.font.Font(None, int(size * 1.3))
    return _fonts[k]


# ----- drawing helpers ---------------------------------------------------

def fill_bg(surface):
    if T.bg2 is None:
        surface.fill(T.bg)
        return
    k = (T.key, surface.get_size())
    grad = _gradients.get(k)
    if grad is None:
        w, h = surface.get_size()
        grad = pygame.Surface((1, max(1, h)))
        for y in range(h):
            grad.set_at((0, y), mix(T.bg, T.bg2, y / max(1, h - 1)))
        grad = pygame.transform.scale(grad, (w, h))
        _gradients.clear()
        _gradients[k] = grad
    surface.blit(grad, (0, 0))


def _glow(surface, rect, color, radius, strength=60, spread=10):
    layer = pygame.Surface((rect.w + spread * 2, rect.h + spread * 2), pygame.SRCALPHA)
    for i in range(spread, 0, -2):
        a = int(strength * (1 - i / spread) ** 2) + 4
        pygame.draw.rect(layer, color + (a,), pygame.Rect(spread - i, spread - i, rect.w + 2 * i,
                                                          rect.h + 2 * i), border_radius=radius + i)
    surface.blit(layer, (rect.x - spread, rect.y - spread))


def panel(surface, rect, alpha=255):
    """A card or a modal box."""
    if T.glow:
        _glow(surface, rect, T.border, T.radius_panel, strength=45, spread=14)
    if alpha < 255:
        box = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(box, T.surface + (alpha,), box.get_rect(), border_radius=T.radius_panel)
        surface.blit(box, rect.topleft)
    else:
        pygame.draw.rect(surface, T.surface, rect, border_radius=T.radius_panel)
    pygame.draw.rect(surface, T.border, rect, 1, border_radius=T.radius_panel)


def button(surface, rect, text, fnt, primary=False, chosen=False, hover=False, active=True):
    """Draws a button; `chosen` is a selected choice (drawn like a primary one)."""
    on = primary or chosen
    radius = min(T.radius, rect.h // 2)
    if not active:
        bg, fg = mix(T.control, T.surface, 0.5), T.muted
    elif on:
        bg, fg = T.accent, T.on_accent
        if hover:
            bg = mix(bg, (255, 255, 255), 0.12)
    else:
        bg, fg = (T.control_hover if hover else T.control), T.text
    if T.outline and not on:
        pygame.draw.rect(surface, T.control_hover if hover else T.bg, rect, border_radius=radius)
        pygame.draw.rect(surface, T.muted if active else T.control, rect, 1, border_radius=radius)
    else:
        if on and T.glow and active:
            _glow(surface, rect, T.accent, radius, strength=70, spread=8)
        pygame.draw.rect(surface, bg, rect, border_radius=radius)
    img = fnt.render(text, True, fg)
    surface.blit(img, img.get_rect(center=rect.center))

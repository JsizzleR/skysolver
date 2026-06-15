#!/usr/bin/env python3
"""
SkySolver — a one-button math-copter game.

Hold SPACE (or the mouse button) to climb; release to descend.
Catch the balloon carrying the right answer to the problem shown at the
bottom of the screen, dodge storm clouds, and grab stars for bonus points
across five skies of rising difficulty.

An original game inspired by the classic "fly into the right answer" genre
of educational copter games. All code, art, and sound are original and
generated at runtime — there are no external assets.

Run:    python skysolver.py
Test:   python skysolver.py --smoke
"""

import math
import os
import random
import struct
import sys

# ---------------------------------------------------------------- constants

W, H = 960, 600
FPS = 60
HUD_H = 84                      # bottom problem banner
PLAY_TOP, PLAY_BOT = 16, H - HUD_H - 16

GRAVITY = 1500.0
THRUST = 3000.0
VY_MAX = 430.0
COPTER_X = 180

LEVELS = 5
CORRECT_PER_LEVEL = 5
START_LIVES = 3
IFRAME_TIME = 1.6

OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_MIXED = "add", "sub", "mul", "div", "mixed"
OPS = [OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_MIXED]
OP_NAMES = {
    OP_ADD: "Addition", OP_SUB: "Subtraction", OP_MUL: "Multiplication",
    OP_DIV: "Division", OP_MIXED: "Mixed (all four)",
}
DIFF_NAMES = ["Breezy", "Steady", "Stormy"]

MENU, PLAY, CLEAR, OVER, WIN = "menu", "play", "clear", "over", "win"

BALLOON_COLORS = [
    (235, 87, 87), (242, 153, 74), (39, 174, 96),
    (45, 156, 219), (155, 89, 182), (230, 126, 168),
]

# per-level sky/sea: sky top, sky bottom, water at horizon, deep water, night
SKIES = [
    ((110, 180, 240), (205, 232, 250), (120, 190, 215), (24, 110, 165), False),
    ((247, 160, 92), (255, 222, 164), (230, 160, 110), (70, 80, 130), False),
    ((92, 72, 142), (202, 142, 162), (150, 110, 150), (50, 55, 105), False),
    ((20, 24, 60), (62, 72, 122), (70, 80, 130), (18, 24, 55), True),
    ((142, 192, 232), (255, 232, 202), (190, 205, 210), (50, 120, 150), False),
]

HORIZON = H - 180

# per-level sun/moon: x fraction, y, radius, color, is_moon
SUNS = [
    (0.78, 90, 34, (255, 240, 180), False),
    (0.70, HORIZON - 50, 44, (255, 180, 90), False),
    (0.62, HORIZON - 26, 30, (255, 200, 150), False),
    (0.75, 90, 26, (235, 235, 225), True),
    (0.66, HORIZON - 60, 38, (255, 230, 170), False),
]

import pygame  # noqa: E402  (env vars may be set before init in smoke mode)

# ------------------------------------------------------------ math problems


class Problem:
    __slots__ = ("text", "answer")

    def __init__(self, text, answer):
        self.text = text
        self.answer = answer


def make_problem(op, level, diff):
    """Build one arithmetic problem scaled by level (1-5) and difficulty (0-2)."""
    if op == OP_MIXED:
        op = random.choice([OP_ADD, OP_SUB, OP_MUL, OP_DIV])
    bump = (0, 2, 5)[diff]
    if op == OP_ADD:
        hi = 5 + 4 * level + 3 * bump
        a, b = random.randint(1, hi), random.randint(1, hi)
        return Problem(f"{a} + {b}", a + b)
    if op == OP_SUB:
        hi = 6 + 4 * level + 3 * bump
        a, b = random.randint(1, hi), random.randint(1, hi)
        if b > a:
            a, b = b, a
        return Problem(f"{a} - {b}", a - b)
    if op == OP_MUL:
        a = random.randint(2, min(12, 2 + level + bump))
        b = random.randint(2, min(12, 3 + level + bump))
        return Problem(f"{a} × {b}", a * b)
    q = random.randint(2, min(12, 2 + level + bump))
    b = random.randint(2, min(12, 3 + level + bump))
    return Problem(f"{q * b} ÷ {b}", q)


def make_distractors(answer, k):
    """k plausible wrong answers: nearby values and common slips."""
    pool = set()
    tries = 0
    while len(pool) < k and tries < 200:
        tries += 1
        d = answer + random.choice([-10, -5, -3, -2, -1, 1, 2, 3, 5, 10,
                                    random.randint(-12, 12)])
        if d != answer and d >= 0:
            pool.add(d)
    while len(pool) < k:                      # tiny answers near zero
        pool.add(answer + len(pool) + 1)
    return list(pool)


# ------------------------------------------------------------------- sound


def _tone_bytes(freq, dur, vol=0.45, rate=22050, shape="sine"):
    n = int(rate * dur)
    out = bytearray()
    attack = max(1, int(n * 0.04))
    release = max(1, int(n * 0.25))
    for i in range(n):
        t = i / rate
        if shape == "square":
            v = 1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0
        else:
            v = math.sin(2 * math.pi * freq * t)
        env = min(1.0, i / attack, (n - i) / release)
        out += struct.pack("<h", int(v * env * vol * 32767))
    return bytes(out)


def _make_sound(*segments):
    try:
        return pygame.mixer.Sound(buffer=b"".join(_tone_bytes(*s) for s in segments))
    except pygame.error:
        return None


# base playback volume per sound (0..1), applied once at build time
SFX_VOLUMES = {
    "correct_whoosh": 0.70, "deflate": 0.55, "thunder": 0.85,
    "splash": 0.70, "rotor_loop": 0.90,
    "star": 0.50, "level": 0.60, "click": 0.40,
}


def build_sounds():
    """Build every sound effect. Rich procedurally-synthesized effects come
    from sfx.py (needs numpy); if that's unavailable we fall back to simple
    pure-Python tones so the game still has audio everywhere."""
    if not pygame.mixer.get_init():
        return {}
    # simple, always-available fallbacks
    sounds = {
        "star": _make_sound((1320, 0.05), (1760, 0.08)),
        "level": _make_sound((523, 0.09), (659, 0.09), (784, 0.09), (1047, 0.18)),
        "click": _make_sound((880, 0.04)),
        "correct_whoosh": _make_sound((660, 0.09), (880, 0.12)),
        "deflate": _make_sound((220, 0.10, 0.5, 22050, "square"),
                               (160, 0.16, 0.5, 22050, "square")),
        "thunder": _make_sound((150, 0.10, 0.5, 22050, "square"),
                               (80, 0.45, 0.6, 22050, "square")),
        "splash": _make_sound((520, 0.06), (300, 0.10), (180, 0.16)),
        "rotor_loop": None,
    }
    # upgrade to the synthesized versions when numpy + sfx are present
    try:
        import numpy as np
        import sfx
        for name, fn in sfx.GENERATORS.items():
            arr = np.ascontiguousarray(fn(sfx.SAMPLE_RATE), dtype="<i2")
            sounds[name] = pygame.mixer.Sound(buffer=arr.tobytes())
    except Exception as exc:        # numpy missing or a generator failed
        print(f"[skysolver] procedural audio unavailable ({exc}); "
              "using simple tones")
    for name, snd in sounds.items():
        if snd:
            snd.set_volume(SFX_VOLUMES.get(name, 0.6))
    return sounds


class SoundBoard:
    """Owns playback: one-shot effects, the looping rotor on a reserved
    channel (volume tracks thrust), and a global mute toggle."""

    ROTOR_IDLE, ROTOR_THRUST = 0.24, 0.42

    def __init__(self, sounds):
        self.sounds = sounds
        self.muted = False
        self.rotor_chan = None
        self.rotor_on = False
        if pygame.mixer.get_init():
            try:
                pygame.mixer.set_num_channels(24)
                pygame.mixer.set_reserved(1)        # keep channel 0 for rotor
                self.rotor_chan = pygame.mixer.Channel(0)
            except pygame.error:
                self.rotor_chan = None

    def play(self, name):
        if self.muted:
            return
        snd = self.sounds.get(name)
        if snd:
            try:
                snd.play()
            except pygame.error:
                pass

    def set_rotor(self, active, thrust):
        chan, rotor = self.rotor_chan, self.sounds.get("rotor_loop")
        if not chan or not rotor:
            return
        if active and not self.muted:
            if not self.rotor_on:
                chan.play(rotor, loops=-1)
                self.rotor_on = True
            chan.set_volume(self.ROTOR_THRUST if thrust else self.ROTOR_IDLE)
        elif self.rotor_on:
            chan.fadeout(150)
            self.rotor_on = False

    def toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            self.set_rotor(False, False)
        return self.muted


# ------------------------------------------------------------ draw helpers

_fonts = {}


def font(size):
    f = _fonts.get(size)
    if f is None:
        f = _fonts[size] = pygame.font.Font(None, size)
    return f


def draw_text(surf, text, size, x, y, color=(255, 255, 255),
              anchor="center", outline=None):
    img = font(size).render(text, True, color)
    rect = img.get_rect(**{anchor: (x, y)})
    if outline:
        oimg = font(size).render(text, True, outline)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            surf.blit(oimg, rect.move(dx, dy))
    surf.blit(img, rect)
    return rect


def vertical_gradient(size, top, bottom):
    w, h = size
    strip = pygame.Surface((1, h))
    for y in range(h):
        f = y / max(1, h - 1)
        strip.set_at((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * f)
                                   for i in range(3)))
    return pygame.transform.scale(strip, (w, h))


def lighten(c, amt):
    return tuple(min(255, ch + amt) for ch in c)


def blend(a, b, f):
    return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))


def draw_swell(surf, color, crest, baseline, amp, wavelength, offset):
    """One rolling wave layer: filled water with a lighter crest line."""
    pts = [(x, baseline + amp * math.sin((x + offset) / wavelength))
           for x in range(0, W + 16, 16)]
    pygame.draw.polygon(surf, color, pts + [(W, H), (0, H)])
    pygame.draw.lines(surf, crest, False, pts, 3)


def draw_sailboat(surf, x, y):
    pygame.draw.polygon(surf, (88, 58, 44),
                        [(x - 16, y), (x + 16, y), (x + 10, y + 7), (x - 10, y + 7)])
    pygame.draw.line(surf, (70, 50, 40), (x, y), (x, y - 22), 2)
    pygame.draw.polygon(surf, (246, 244, 236),
                        [(x + 2, y - 22), (x + 2, y - 4), (x + 15, y - 6)])
    pygame.draw.polygon(surf, (228, 222, 210),
                        [(x - 2, y - 20), (x - 2, y - 5), (x - 12, y - 7)])


def draw_copter(surf, x, y, vy, t, blink=False):
    if blink and int(t * 10) % 2 == 0:
        return
    body = pygame.Surface((150, 96), pygame.SRCALPHA)
    cx, cy = 88, 56
    pygame.draw.line(body, (40, 90, 90), (cx - 64, cy - 4), (cx - 20, cy), 7)
    pygame.draw.polygon(body, (60, 130, 130),
                        [(cx - 70, cy - 18), (cx - 56, cy - 4), (cx - 70, cy - 2)])
    pygame.draw.circle(body, (200, 210, 220), (cx - 68, cy - 10), 7, 2)
    pygame.draw.ellipse(body, (52, 168, 158), (cx - 34, cy - 20, 72, 42))
    pygame.draw.ellipse(body, (235, 245, 245), (cx + 6, cy - 14, 26, 18))
    pygame.draw.line(body, (40, 90, 90), (cx - 18, cy + 20), (cx - 22, cy + 30), 4)
    pygame.draw.line(body, (40, 90, 90), (cx + 16, cy + 20), (cx + 20, cy + 30), 4)
    pygame.draw.line(body, (70, 110, 110), (cx - 34, cy + 31), (cx + 34, cy + 31), 5)
    pygame.draw.line(body, (40, 90, 90), (cx, cy - 20), (cx, cy - 28), 4)
    span = int(56 * abs(math.sin(t * 22)) + 12)
    pygame.draw.line(body, (30, 60, 60), (cx - span, cy - 29), (cx + span, cy - 29), 4)
    angle = max(-12.0, min(12.0, -vy * 0.022))
    rotated = pygame.transform.rotozoom(body, angle, 1.0)
    surf.blit(rotated, rotated.get_rect(center=(x, y)))


def draw_balloon(surf, b, t):
    x, y = int(b.x), int(b.y)
    r = b.radius
    sway = math.sin(t * 2.2 + b.phase) * 4
    pygame.draw.line(surf, (90, 90, 100), (x, y + r), (x + sway, y + r + 26), 2)
    pygame.draw.circle(surf, b.color, (x, y), r)
    hi = tuple(min(255, c + 55) for c in b.color)
    pygame.draw.circle(surf, hi, (x - r // 3, y - r // 3), r // 3)
    pygame.draw.polygon(surf, b.color,
                        [(x - 6, y + r), (x + 6, y + r), (x, y + r + 8)])
    draw_text(surf, str(b.value), 30, x, y, (255, 255, 255),
              outline=(40, 40, 50))


def draw_storm_cloud(surf, c, t):
    x, y = int(c.x), int(c.y + math.sin(t * 1.7 + c.phase) * 6)
    for dx, dy, r in ((-26, 4, 20), (0, -8, 26), (26, 4, 20), (0, 8, 24)):
        pygame.draw.circle(surf, (110, 115, 130), (x + dx, y + dy), r)
    for dx, dy, r in ((-24, 2, 16), (0, -10, 21), (24, 2, 16)):
        pygame.draw.circle(surf, (140, 145, 160), (x + dx, y + dy - 4), r)
    bolt = [(x - 4, y + 18), (x + 8, y + 18), (x, y + 34),
            (x + 10, y + 34), (x - 8, y + 56), (x - 2, y + 38),
            (x - 12, y + 38)]
    pygame.draw.polygon(surf, (255, 216, 70), bolt)


def draw_star_pickup(surf, s, t):
    x = s.x
    y = s.y + math.sin(t * 3 + s.phase) * 8
    pygame.draw.circle(surf, (255, 240, 160, 60), (int(x), int(y)), 22, 0)
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5 + t * 1.5
        rad = 16 if i % 2 == 0 else 7
        pts.append((x + rad * math.cos(ang), y + rad * math.sin(ang)))
    pygame.draw.polygon(surf, (255, 205, 40), pts)
    pygame.draw.polygon(surf, (255, 240, 160), pts, 2)


def draw_heart(surf, x, y, filled):
    color = (235, 80, 100) if filled else (120, 120, 130)
    pygame.draw.circle(surf, color, (x - 5, y - 3), 7)
    pygame.draw.circle(surf, color, (x + 5, y - 3), 7)
    pygame.draw.polygon(surf, color, [(x - 11, y), (x + 11, y), (x, y + 13)])


# ---------------------------------------------------------------- entities


class Balloon:
    def __init__(self, value, correct, speed, y=None, x=None):
        self.value = value
        self.correct = correct
        self.x = W + 50 if x is None else x
        self.y = random.uniform(PLAY_TOP + 60, PLAY_BOT - 60) if y is None else y
        self.vx = -speed * random.uniform(0.9, 1.15)
        self.radius = 30
        self.color = random.choice(BALLOON_COLORS)
        self.phase = random.uniform(0, 6.28)
        self.dying = False
        self.vy = 0.0

    def update(self, dt):
        if self.dying:
            self.vy -= 700 * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

    @property
    def gone(self):
        return self.x < -60 or self.y < -80


class Drifter:
    """Shared base for clouds and stars: drifts left, bobs in place."""

    def __init__(self, speed, radius):
        self.x = W + 60
        self.y = random.uniform(PLAY_TOP + 50, PLAY_BOT - 50)
        self.vx = -speed
        self.radius = radius
        self.phase = random.uniform(0, 6.28)

    def update(self, dt):
        self.x += self.vx * dt

    @property
    def gone(self):
        return self.x < -80


# ------------------------------------------------------------------- game


class Game:
    def __init__(self):
        pygame.mixer.pre_init(22050, -16, 1, 512)
        pygame.init()
        try:
            pygame.mixer.init()
        except pygame.error:
            pass
        pygame.display.set_caption("SkySolver")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.sounds = build_sounds()
        self.sfx = SoundBoard(self.sounds)
        self.sky_cache = {}
        self.water_cache = {}
        self.best_score = 0
        self.state = MENU
        self.menu_index = 0
        self.difficulty = 1
        self.t = 0.0
        self.thrust_input = False
        self.reset_run()

    # ------------------------------------------------------------- helpers

    def play_sound(self, name):
        self.sfx.play(name)

    def sky(self, level):
        key = level
        if key not in self.sky_cache:
            top, bottom, *_ = SKIES[level - 1]
            self.sky_cache[key] = vertical_gradient((W, H), top, bottom)
        return self.sky_cache[key]

    def water(self, level):
        if level not in self.water_cache:
            _, _, far, near, _ = SKIES[level - 1]
            self.water_cache[level] = vertical_gradient((W, H - HORIZON),
                                                        far, near)
        return self.water_cache[level]

    def draw_ocean(self, level):
        surf = self.screen
        _, _, far, near, night = SKIES[level - 1]
        xf, sy, sr, scolor, is_moon = SUNS[level - 1]
        sx = int(W * xf)

        # sun or moon, with a soft glow
        glow = pygame.Surface((sr * 6, sr * 6), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*scolor, 36), (sr * 3, sr * 3), sr * 3)
        pygame.draw.circle(glow, (*scolor, 60), (sr * 3, sr * 3), int(sr * 1.7))
        surf.blit(glow, (sx - sr * 3, sy - sr * 3))
        pygame.draw.circle(surf, scolor, (sx, sy), sr)
        if is_moon:
            shadow = blend(scolor, SKIES[level - 1][0], 0.92)
            pygame.draw.circle(surf, shadow, (sx + sr // 2, sy - sr // 4),
                               int(sr * 0.85))

        # distant islands drifting just above the horizon
        rng = random.Random(level * 31)
        island_color = blend(far, (38, 40, 58), 0.45)
        for i in range(rng.randint(1, 2)):
            base = rng.randint(0, W)
            iw = rng.randint(80, 150)
            ix = int((base - self.t * 5) % (W + 240)) - 120
            pygame.draw.ellipse(surf, island_color,
                                (ix, HORIZON - 13, iw, 26))

        # the water itself
        surf.blit(self.water(level), (0, HORIZON))

        # shimmering reflection column under the sun/moon
        refl = blend(scolor, near, 0.35)
        for row in range(HORIZON + 10, H, 14):
            wob = math.sin(self.t * 2.0 + row * 0.45)
            half = int(sr * (0.7 + 0.45 * wob) * (1.0 - (row - HORIZON) / 600))
            if half > 3:
                pygame.draw.ellipse(surf, refl, (sx - half, row, half * 2, 4))

        # rolling swells
        mid = blend(far, near, 0.5)
        draw_swell(surf, mid, lighten(mid, 38), HORIZON + 28, 8, 70,
                   self.t * 30)
        draw_swell(surf, near, lighten(near, 30), HORIZON + 64, 12, 55,
                   self.t * 55)

        # a little sailboat tacking along the first swell
        bx = W + 150 - ((self.t * 14 + 200) % (W + 300))
        by = HORIZON + 24 + 8 * math.sin((bx + self.t * 30) / 70) \
            + math.sin(self.t * 1.8) * 2
        draw_sailboat(surf, bx, by - 6)

        # twinkling glints on the water
        grng = random.Random(level * 97)
        glint = lighten(far, 70) if not night else (210, 215, 235)
        for i in range(40):
            gx = grng.randint(0, W)
            gy = grng.randint(HORIZON + 14, H - 10)
            if math.sin(self.t * 2.2 + i * 1.7) > 0.45:
                pygame.draw.ellipse(surf, glint, (gx, gy, 5, 2))

    # --------------------------------------------------------------- state

    def reset_run(self):
        self.level = 1
        self.score = 0
        self.lives = START_LIVES
        self.streak = 0
        self.solved_in_level = 0
        self.copter_y = H / 2
        self.copter_vy = 0.0
        self.iframes = 0.0
        self.balloons = []
        self.clouds = []
        self.stars = []
        self.particles = []
        self.float_texts = []
        self.spawn_queue = []
        self.spawn_timer = 0.0
        self.cloud_timer = 4.0
        self.star_timer = 6.0
        self.clear_timer = 0.0
        self.problem = None

    def start_run(self):
        self.reset_run()
        self.new_problem()
        self.state = PLAY

    def speed_factor(self):
        return ((0.85, 1.0, 1.2)[self.difficulty]
                * (1.0 + 0.15 * (self.level - 1)))

    def new_problem(self):
        op = OPS[self.menu_index]
        self.problem = make_problem(op, self.level, self.difficulty)
        self.new_wave()

    def new_wave(self):
        n = 4 + (1 if self.level >= 3 else 0)
        values = [self.problem.answer] + make_distractors(self.problem.answer, n - 1)
        random.shuffle(values)
        self.spawn_queue = values
        self.spawn_timer = 0.5

    # --------------------------------------------------------------- events

    def handle_event(self, ev):
        if ev.type == pygame.QUIT:
            raise SystemExit
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_m:               # mute/unmute from anywhere
            self.sfx.toggle_mute()
            return
        if self.state == MENU:
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.menu_index = (self.menu_index - 1) % len(OPS)
                self.play_sound("click")
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.menu_index = (self.menu_index + 1) % len(OPS)
                self.play_sound("click")
            elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_d):
                step = -1 if ev.key == pygame.K_LEFT else 1
                self.difficulty = (self.difficulty + step) % 3
                self.play_sound("click")
            elif ev.key in (pygame.K_1, pygame.K_2, pygame.K_3,
                            pygame.K_4, pygame.K_5):
                self.menu_index = ev.key - pygame.K_1
                self.start_run()
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.start_run()
            elif ev.key == pygame.K_ESCAPE:
                raise SystemExit
        elif self.state in (OVER, WIN):
            if ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.state = MENU
            elif ev.key == pygame.K_ESCAPE:
                raise SystemExit
        elif self.state == PLAY and ev.key == pygame.K_ESCAPE:
            self.state = MENU

    # --------------------------------------------------------------- update

    def update(self, dt):
        self.t += dt
        if self.state == PLAY:
            self.update_play(dt)
        elif self.state == CLEAR:
            self.clear_timer -= dt
            self.update_effects(dt)
            if self.clear_timer <= 0:
                self.level += 1
                self.solved_in_level = 0
                self.balloons.clear()
                self.clouds.clear()
                self.stars.clear()
                self.new_problem()
                self.state = PLAY

    def update_play(self, dt):
        # copter physics
        accel = GRAVITY - (THRUST if self.thrust_input else 0.0)
        self.copter_vy = max(-VY_MAX, min(VY_MAX, self.copter_vy + accel * dt))
        self.copter_y += self.copter_vy * dt
        # ceiling: a harmless bonk against the top of the sky
        if self.copter_y < PLAY_TOP + 34:
            self.copter_y, self.copter_vy = PLAY_TOP + 34, 0.0
        # water: you can't rest on the sea — ditching in it is a crash
        if self.copter_y > PLAY_BOT - 28:
            self.copter_y = PLAY_BOT - 28
            if self.iframes <= 0:
                self.copter_vy = -VY_MAX            # bounce back up
                self.burst(COPTER_X, PLAY_BOT - 14, (180, 220, 240), 20)
                self.lose_life(COPTER_X, PLAY_BOT - 30, "splash!", sound="splash")
            else:
                self.copter_vy = min(self.copter_vy, 0.0)
        self.iframes = max(0.0, self.iframes - dt)

        # spawning
        speed = 120 * self.speed_factor()
        self.spawn_timer -= dt
        if self.spawn_queue and self.spawn_timer <= 0:
            value = self.spawn_queue.pop(0)
            self.balloons.append(Balloon(value, value == self.problem.answer, speed))
            self.spawn_timer = random.uniform(0.8, 1.3) / self.speed_factor()
        live = [b for b in self.balloons if not b.dying]
        if not self.spawn_queue and not live:
            self.new_wave()

        self.cloud_timer -= dt
        if self.cloud_timer <= 0:
            self.clouds.append(Drifter(speed * 1.35, 40))
            base = max(1.6, 5.4 - 0.7 * self.level - 0.4 * self.difficulty)
            self.cloud_timer = random.uniform(base, base + 2.0)
        self.star_timer -= dt
        if self.star_timer <= 0:
            self.stars.append(Drifter(speed * 1.1, 20))
            self.star_timer = random.uniform(5.0, 9.0)

        # movement
        for group in (self.balloons, self.clouds, self.stars):
            for e in group:
                e.update(dt)
            group[:] = [e for e in group if not e.gone]
        self.update_effects(dt)

        # collisions
        cx, cy = COPTER_X, self.copter_y
        for b in self.balloons:
            if b.dying:
                continue
            if math.hypot(b.x - cx, b.y - cy) < b.radius + 26:
                self.on_balloon(b)
        if self.iframes <= 0:
            for c in self.clouds:
                if math.hypot(c.x - cx, c.y - cy) < c.radius + 20:
                    self.lose_life(c.x, c.y, "zap!", sound="thunder")
                    break
        for s in self.stars[:]:
            if math.hypot(s.x - cx, s.y - cy) < s.radius + 26:
                self.stars.remove(s)
                self.score += 50
                self.add_float("+50", s.x, s.y, (255, 215, 80))
                self.burst(s.x, s.y, (255, 215, 80), 14)
                self.play_sound("star")

    def on_balloon(self, b):
        if b.correct:
            self.streak += 1
            points = 100 * min(self.streak, 5)
            self.score += points
            self.best_score = max(self.best_score, self.score)
            self.add_float(f"+{points}", b.x, b.y, (120, 240, 140))
            self.burst(b.x, b.y, b.color, 20)
            self.play_sound("correct_whoosh")
            self.balloons.remove(b)
            for other in self.balloons:
                other.dying = True
            self.solved_in_level += 1
            if self.solved_in_level >= CORRECT_PER_LEVEL:
                if self.level >= LEVELS:
                    self.state = WIN
                    self.play_sound("level")
                else:
                    self.state = CLEAR
                    self.clear_timer = 2.4
                    self.play_sound("level")
            else:
                self.new_problem()
        elif self.iframes <= 0:
            self.burst(b.x, b.y, b.color, 12)
            self.balloons.remove(b)
            self.lose_life(b.x, b.y, "pop!", sound="deflate")

    def lose_life(self, x, y, msg="ouch!", sound="deflate"):
        self.lives -= 1
        self.streak = 0
        self.iframes = IFRAME_TIME
        self.add_float(msg, x, y, (255, 120, 120))
        self.burst(COPTER_X, self.copter_y, (160, 160, 170), 16)
        self.play_sound(sound)
        if self.lives <= 0:
            self.state = OVER

    # -------------------------------------------------------------- effects

    def add_float(self, text, x, y, color):
        self.float_texts.append({"text": text, "x": x, "y": y,
                                 "color": color, "life": 1.1})

    def burst(self, x, y, color, n):
        for _ in range(n):
            ang = random.uniform(0, 6.28)
            spd = random.uniform(60, 260)
            self.particles.append({
                "x": x, "y": y, "vx": math.cos(ang) * spd,
                "vy": math.sin(ang) * spd, "life": random.uniform(0.3, 0.8),
                "color": color, "r": random.randint(2, 5),
            })

    def update_effects(self, dt):
        for p in self.particles:
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 500 * dt
            p["life"] -= dt
        self.particles = [p for p in self.particles if p["life"] > 0]
        for f in self.float_texts:
            f["y"] -= 50 * dt
            f["life"] -= dt
        self.float_texts = [f for f in self.float_texts if f["life"] > 0]

    # ---------------------------------------------------------------- draw

    def draw_world(self):
        level = min(self.level, LEVELS)
        night = SKIES[level - 1][4]
        self.screen.blit(self.sky(level), (0, 0))
        if night:
            rng = random.Random(7)
            for _ in range(60):
                x, y = rng.randint(0, W), rng.randint(0, HORIZON - 12)
                self.screen.set_at((x, y), (230, 230, 245))
        self.draw_ocean(level)

        for b in self.balloons:
            draw_balloon(self.screen, b, self.t)
        for s in self.stars:
            draw_star_pickup(self.screen, s, self.t)
        for c in self.clouds:
            draw_storm_cloud(self.screen, c, self.t)
        draw_copter(self.screen, COPTER_X, self.copter_y, self.copter_vy,
                    self.t, blink=self.iframes > 0)

        for p in self.particles:
            pygame.draw.circle(self.screen, p["color"],
                               (int(p["x"]), int(p["y"])), p["r"])
        for f in self.float_texts:
            draw_text(self.screen, f["text"], 30, f["x"], f["y"],
                      f["color"], outline=(30, 30, 40))

    def draw_hud(self):
        banner = pygame.Surface((W, HUD_H), pygame.SRCALPHA)
        banner.fill((20, 30, 45, 215))
        self.screen.blit(banner, (0, H - HUD_H))
        if self.problem:
            draw_text(self.screen, f"{self.problem.text} = ?", 56,
                      W // 2, H - HUD_H // 2, (255, 255, 255))
        draw_text(self.screen, f"Score {self.score}", 32, 16, 14,
                  (255, 255, 255), anchor="topleft", outline=(30, 30, 40))
        if self.streak >= 2:
            draw_text(self.screen, f"streak ×{min(self.streak, 5)}", 26,
                      16, 44, (255, 220, 120), anchor="topleft",
                      outline=(30, 30, 40))
        draw_text(self.screen,
                  f"Level {self.level}   {self.solved_in_level}/{CORRECT_PER_LEVEL}",
                  32, W // 2, 14, (255, 255, 255), anchor="midtop",
                  outline=(30, 30, 40))
        for i in range(START_LIVES):
            draw_heart(self.screen, W - 30 - i * 30, 26, i < self.lives)
        if self.sfx.muted:
            draw_text(self.screen, "muted (M)", 24, W - 16, 52,
                      (255, 180, 160), anchor="topright", outline=(30, 30, 40))

    def draw_menu(self):
        self.screen.blit(self.sky(1), (0, 0))
        self.draw_ocean(1)
        bob = math.sin(self.t * 1.4) * 10
        draw_copter(self.screen, W - 200, 150 + bob, -bob * 6, self.t)
        draw_text(self.screen, "SkySolver", 92, W // 2, 90,
                  (255, 255, 255), outline=(40, 80, 110))
        draw_text(self.screen, "catch the right answer — dodge the storms",
                  30, W // 2, 148, (240, 248, 255), outline=(40, 80, 110))
        for i, op in enumerate(OPS):
            y = 230 + i * 46
            selected = i == self.menu_index
            if selected:
                pygame.draw.rect(self.screen, (255, 255, 255, 40),
                                 (W // 2 - 190, y - 19, 380, 38),
                                 border_radius=10, width=3)
            color = (255, 230, 120) if selected else (255, 255, 255)
            draw_text(self.screen, f"{i + 1}.  {OP_NAMES[op]}", 36,
                      W // 2, y, color, outline=(40, 80, 110))
        draw_text(self.screen,
                  f"difficulty:  < {DIFF_NAMES[self.difficulty]} >", 32,
                  W // 2, 480, (255, 255, 255), outline=(40, 80, 110))
        draw_text(self.screen,
                  "↑/↓ choose · ←/→ difficulty · ENTER start",
                  26, W // 2, 524, (235, 242, 250), outline=(40, 80, 110))
        draw_text(self.screen,
                  "in flight: hold SPACE/mouse to climb — don't ditch in the sea!",
                  26, W // 2, 552, (235, 242, 250), outline=(40, 80, 110))
        snd_txt = "sound: OFF  (M)" if self.sfx.muted else "sound: ON  (M)"
        snd_col = (255, 170, 150) if self.sfx.muted else (170, 235, 180)
        draw_text(self.screen, snd_txt, 26, W // 2, 578, snd_col,
                  outline=(40, 80, 110))
        if self.best_score:
            draw_text(self.screen, f"best this session: {self.best_score}",
                      26, W // 2, 196, (255, 230, 120), outline=(40, 80, 110))

    def draw_overlay(self, title, subtitle, color):
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((15, 20, 35, 170))
        self.screen.blit(veil, (0, 0))
        draw_text(self.screen, title, 84, W // 2, H // 2 - 70, color,
                  outline=(20, 20, 30))
        draw_text(self.screen, f"final score: {self.score}", 40,
                  W // 2, H // 2 + 4, (255, 255, 255), outline=(20, 20, 30))
        draw_text(self.screen, subtitle, 30, W // 2, H // 2 + 60,
                  (230, 235, 245), outline=(20, 20, 30))

    def draw(self):
        if self.state == MENU:
            self.draw_menu()
        else:
            self.draw_world()
            self.draw_hud()
            if self.state == CLEAR:
                draw_text(self.screen, f"Sky {self.level} clear!", 72,
                          W // 2, H // 2 - 30, (255, 230, 120),
                          outline=(40, 50, 70))
                draw_text(self.screen, "get ready...", 34, W // 2, H // 2 + 30,
                          (255, 255, 255), outline=(40, 50, 70))
            elif self.state == OVER:
                self.draw_overlay("Out of lives", "ENTER for menu",
                                  (255, 140, 130))
            elif self.state == WIN:
                self.draw_overlay("All five skies cleared!",
                                  "ENTER for menu", (140, 240, 160))
        pygame.display.flip()

    # ----------------------------------------------------------------- run

    def run(self):
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            for ev in pygame.event.get():
                self.handle_event(ev)
            keys = pygame.key.get_pressed()
            self.thrust_input = (keys[pygame.K_SPACE] or keys[pygame.K_UP]
                                 or pygame.mouse.get_pressed()[0])
            self.update(dt)
            self.sfx.set_rotor(self.state in (PLAY, CLEAR), self.thrust_input)
            self.draw()


# ------------------------------------------------------------------ smoke


def run_smoke():
    """Headless self-test: validates problem generation and exercises every
    game state and collision path without a real window or audio device."""
    random.seed(11)

    # 1. every generated problem must be arithmetically true with valid text
    for op in OPS:
        for level in range(1, LEVELS + 1):
            for diff in range(3):
                for _ in range(150):
                    p = make_problem(op, level, diff)
                    expr = p.text.replace("×", "*").replace("÷", "/")
                    assert eval(expr) == p.answer, (p.text, p.answer)
                    assert p.answer >= 0
                    ds = make_distractors(p.answer, 4)
                    assert len(set(ds)) == 4 and p.answer not in ds
                    assert all(d >= 0 for d in ds)

    game = Game()
    dt = 1 / 60

    # 2. menu frames + navigation
    for _ in range(30):
        game.update(dt)
        game.draw()
    game.menu_index, game.difficulty = 4, 2          # mixed, stormy
    game.start_run()
    assert game.state == PLAY and game.problem is not None

    # 3. free flight, hovering around mid-screen — never touches the sea.
    # balloons/clouds are cleared each frame to isolate the flight physics.
    for _ in range(400):
        game.thrust_input = game.copter_y > H / 2
        game.balloons.clear()
        game.clouds.clear()
        game.update(dt)
        game.draw()
    assert PLAY_TOP < game.copter_y < PLAY_BOT
    assert game.state == PLAY and game.lives == START_LIVES

    # 3b. ditching in the water costs a life and bounces the copter up
    game.thrust_input = False
    crashed = False
    for _ in range(180):                           # let it fall onto the sea
        game.balloons.clear()
        game.clouds.clear()                        # water is the only hazard
        game.update(dt)
        if game.lives < START_LIVES:
            crashed = True
            break
    assert crashed and game.lives == START_LIVES - 1
    assert game.copter_vy < 0                       # bounced upward
    assert game.iframes > 0                         # briefly invulnerable

    # 3c. while invulnerable the sea only clamps — no extra lives lost
    lives_after_crash = game.lives
    for _ in range(8):
        game.copter_y = PLAY_BOT                     # pin onto the water
        game.clouds.clear()
        game.update(dt)
    assert game.lives == lives_after_crash

    # 4. catch correct answers through level clears up to the win screen
    game.start_run()
    while game.state in (PLAY, CLEAR):
        if game.state == CLEAR:
            game.update(dt)
            continue
        game.copter_y, game.copter_vy = H / 2, 0.0  # hold steady at center
        game.balloons.append(Balloon(game.problem.answer, True, 120,
                                     y=game.copter_y, x=COPTER_X))
        game.update(dt)
        game.draw()
    assert game.state == WIN, game.state
    assert game.score >= 25 * 100

    # 5. wrong balloon, storm cloud, star pickup, game over
    game.start_run()
    wrong = make_distractors(game.problem.answer, 1)[0]
    game.balloons.append(Balloon(wrong, False, 120, y=game.copter_y, x=COPTER_X))
    game.update(dt)
    assert game.lives == START_LIVES - 1 and game.streak == 0
    game.iframes = 0
    cloud = Drifter(120, 40)
    cloud.x, cloud.y = COPTER_X, game.copter_y
    game.clouds.append(cloud)
    game.update(dt)
    assert game.lives == START_LIVES - 2
    star = Drifter(120, 20)
    star.x, star.y = COPTER_X, game.copter_y
    game.stars.append(star)
    before = game.score
    game.update(dt)
    assert game.score == before + 50
    game.iframes = 0
    game.clouds.append(cloud)
    game.update(dt)
    assert game.state == OVER and game.lives == 0
    game.draw()

    # 6. sound board: every event sound, the rotor, and mute toggling
    for name in ("correct_whoosh", "deflate", "thunder", "splash",
                 "rotor_loop", "star", "level", "click"):
        game.sfx.play(name)                          # must never raise
    game.sfx.set_rotor(True, True)
    game.sfx.set_rotor(True, False)
    game.sfx.set_rotor(False, False)
    assert game.sfx.toggle_mute() is True
    game.sfx.play("thunder")                         # silently ignored
    game.sfx.set_rotor(True, True)
    assert game.sfx.toggle_mute() is False

    print("SMOKE PASS")


def main():
    if "--smoke" in sys.argv:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        run_smoke()
        return
    Game().run()


if __name__ == "__main__":
    main()

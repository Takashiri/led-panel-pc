"""Pixel transitions for the LED panel and its preview."""

import io
import random
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from PIL import Image


class Transition(StrEnum):
    NONE = "none"
    SLIDE_LEFT = "slide-left"
    SLIDE_RIGHT = "slide-right"
    SLIDE_UP = "slide-up"
    SLIDE_DOWN = "slide-down"
    WIPE_LEFT = "wipe-left"
    CENTER = "center"
    BLINDS = "blinds"
    CHECKERBOARD = "checkerboard"
    PIXELS = "pixels"
    FADE = "fade"


class TransitionSpeed(StrEnum):
    QUICK = "quick"
    BALANCED = "balanced"
    SMOOTH = "smooth"


TRANSITION_LABELS = {
    Transition.NONE: "Bez animace",
    Transition.SLIDE_LEFT: "Posun doleva",
    Transition.SLIDE_RIGHT: "Posun doprava",
    Transition.SLIDE_UP: "Posun nahoru",
    Transition.SLIDE_DOWN: "Posun dolů",
    Transition.WIPE_LEFT: "Stěr zleva",
    Transition.CENTER: "Rozevření od středu",
    Transition.BLINDS: "Žaluzie",
    Transition.CHECKERBOARD: "Šachovnice",
    Transition.PIXELS: "Odhalení po pixelech",
    Transition.FADE: "Prolnutí přes černou",
}
SPEED_LABELS = {
    TransitionSpeed.QUICK: "Rychlá (0,36 s)",
    TransitionSpeed.BALANCED: "Vyvážená (0,50 s)",
    TransitionSpeed.SMOOTH: "Plynulá (0,64 s)",
}
TIMING = {TransitionSpeed.QUICK: (6, 60), TransitionSpeed.BALANCED: (10, 50), TransitionSpeed.SMOOTH: (16, 40)}
DIRECTIONS = {
    Transition.SLIDE_LEFT: (-1, 0), Transition.SLIDE_RIGHT: (1, 0),
    Transition.SLIDE_UP: (0, -1), Transition.SLIDE_DOWN: (0, 1),
}


@dataclass(frozen=True)
class Animation:
    frames: tuple[Image.Image, ...]
    frame_ms: int

    @property
    def duration(self):
        return len(self.frames) * self.frame_ms / 1000

    def panel_gif(self):
        durations = [self.frame_ms] * len(self.frames)
        # The panel library always writes a loop count. Hold the final frame
        # while the app sends the destination page's normal image or ticker.
        durations[-1] += 2000
        with io.BytesIO() as buffer:
            self.frames[0].save(buffer, format="GIF", save_all=True,
                                append_images=self.frames[1:], duration=durations, loop=1, disposal=2)
            return buffer.getvalue().hex()


@lru_cache(maxsize=20)
def reveal_order(effect, size):
    width, height = size
    count = width * height
    if effect is Transition.PIXELS:
        order = list(range(count))
        random.Random(0).shuffle(order)
        return tuple(rank / count for rank in order)
    if effect is Transition.WIPE_LEFT:
        return tuple(x / width for _ in range(height) for x in range(width))
    if effect is Transition.CENTER:
        return tuple(abs(2 * x + 1 - width) / width for _ in range(height) for x in range(width))
    if effect is Transition.BLINDS:
        return tuple((x % 16) / 16 for _ in range(height) for x in range(width))
    if effect is Transition.CHECKERBOARD:
        return tuple(((x // 8 + y // 4) % 2) / 2 + (x % 8) / 16
                     for y in range(height) for x in range(width))
    raise ValueError(f"Unknown reveal transition: {effect}")


def render_transition(source, target, effect, progress):
    if progress <= 0:
        return source
    if progress >= 1 or effect is Transition.NONE:
        return target
    if effect in DIRECTIONS:
        width, height = source.size
        x, y = DIRECTIONS[effect]
        dx, dy = round(width * progress) * x, round(height * progress) * y
        frame = Image.new("RGB", source.size)
        frame.paste(source, (dx, dy))
        frame.paste(target, (dx - width * x, dy - height * y))
        return frame
    if effect is Transition.FADE:
        frame = source if progress < 0.5 else target
        return Image.blend(Image.new("RGB", source.size), frame, abs(2 * progress - 1))
    mask = Image.frombytes("L", source.size, bytes(255 if rank < progress else 0
                                                  for rank in reveal_order(effect, source.size)))
    return Image.composite(target, source, mask)


def make_transition(source, target, effect, speed):
    count, delay = TIMING[speed]
    progress = [index / (count - 1) for index in range(count)]
    if effect is Transition.FADE:
        progress[count // 2] = 0.5
    frames = tuple(render_transition(source, target, effect, step) for step in progress)
    return Animation(frames, delay)

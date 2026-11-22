"""Building blocks every effect uses: the canvas context, the Element base class, easing and colour helpers.

An Element owns a rectangle of the canvas (x, y, w, h in source pixels) and a time span (start, end),
and returns an RGBA image of that rectangle for any time t via draw(t). That's the whole contract —
the renderer handles frames, encoding, caching and compositing.

Sizes are written in "1080p units" and multiplied by ctx.u, so one design looks the same on
1080p / 4K / landscape / portrait footage.
"""

from __future__ import annotations

import hashlib
import json
import math

from PIL import Image

from . import fonts


# ----------------------------------------------------------------------------- helpers
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    """Fast start, soft landing. The default for anything appearing."""
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_out_back(x, s=1.7):
    """Overshoots a little then settles — a 'pop'. Use for things that should feel lively."""
    x = clamp(x) - 1
    return x * x * ((s + 1) * x + s) + 1


def fade_in_out(lt, dur, fin=0.25, fout=0.25):
    """Opacity 0..1 for local time lt in an element that lasts dur seconds."""
    return min(ease_out(lt / fin) if fin > 0 else 1.0, 1 - clamp((lt - (dur - fout)) / fout) if fout > 0 else 1.0)


def even(v):
    v = int(round(v))
    return v + (v % 2)


def hex_rgb(s, default=(255, 196, 61)):
    try:
        s = str(s).strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def mix(a, b, k):
    return tuple(int(a[i] * (1 - k) + b[i] * k) for i in range(3))


def rgba(c, a):
    return tuple(c[:3]) + (int(clamp(a, 0, 255)),)


# ----------------------------------------------------------------------------- context
class Ctx:
    def __init__(self, meta: dict, style: dict | None = None):
        style = style or {}
        self.meta = meta
        self.W, self.H = meta["width"], meta["height"]
        self.duration = meta["duration"]
        self.fps = meta["fps"] if meta["fps"] <= 30.5 else 30.0
        self.u = min(self.W, self.H) / 1080.0
        self.portrait = self.H > self.W
        self.accent = hex_rgb(style.get("accent", "#FFC43D"))
        self.dark = hex_rgb(style.get("dark", "#1E1A16"), (30, 26, 22))
        self.light = (245, 242, 236)
        self.font_ui = style.get("font", "") or ""
        self.font_title = style.get("title_font", "") or ""
        self.style = style
        self.safe_top = 0

    def font(self, kind, size_1080):
        """kind: 'ui' (bold sans) or 'title' (display face if installed). size in 1080p units."""
        return fonts.get(kind, int(size_1080 * self.u), self.font_ui, self.font_title)

    def sig(self):
        return dict(W=self.W, H=self.H, fps=self.fps, accent=self.accent, dark=self.dark,
                    f=[str(x) for x in fonts.resolve(self.font_ui, self.font_title).values()])


class Element:
    kind = "element"
    label = ""
    layer = 50          # higher = drawn on top
    scale = 1.0         # render scale; soft full-frame effects can use 0.5 and get upscaled by ffmpeg

    def __init__(self, ctx: Ctx, spec: dict):
        self.ctx = ctx
        self.spec = spec
        self.start = float(spec.get("start", 0.0))
        self.end = float(spec.get("end", ctx.duration))
        self.x = self.y = 0
        self.w, self.h = ctx.W, ctx.H
        self.sfx: list[tuple[float, str, float]] = []   # (time, 'ding'|'pop'|'whoosh', gain)
        self.label = spec.get("label_for_sheet") or self.label or self.kind

    # identity for the clip cache: any change to spec / region / canvas / code re-renders
    def key(self) -> str:
        blob = json.dumps([type(self).__name__, self.kind, self.spec, self.start, self.end, self.x, self.y, self.w,
                           self.h, self.scale, self.ctx.sig(), self.extra_sig(), getattr(self, "_src_hash", None)],
                          sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]

    def extra_sig(self):
        return None

    @property
    def size(self):
        return max(2, even(self.w * self.scale)), max(2, even(self.h * self.scale))

    def blank(self):
        return Image.new("RGBA", self.size, (0, 0, 0, 0))

    def draw(self, t: float) -> Image.Image:
        raise NotImplementedError

    def preview_time(self) -> float:
        return (self.start + self.end) / 2

    def fit_region(self, x0, y0, x1, y1):
        """Shrink the element's rectangle to this box (clamped to the canvas). Smaller = faster."""
        W, H = self.ctx.W, self.ctx.H
        x0, y0 = max(0, int(x0)) // 2 * 2, max(0, int(y0)) // 2 * 2
        x1, y1 = min(W, int(math.ceil(x1))), min(H, int(math.ceil(y1)))
        self.x, self.y = x0, y0
        self.w, self.h = max(2, even(x1 - x0)), max(2, even(y1 - y0))
        if self.x + self.w > W:
            self.w = (W - self.x) // 2 * 2
        if self.y + self.h > H:
            self.h = (H - self.y) // 2 * 2


def composite_still(els: list[Element], base: Image.Image, t: float) -> Image.Image:
    img = base.convert("RGBA")
    for e in els:
        if e.start <= t < e.end:
            o = e.draw(t)
            if o.size != (e.w, e.h):
                o = o.resize((e.w, e.h), Image.BILINEAR)
            img.alpha_composite(o, (e.x, e.y))
    return img.convert("RGB")

"""Example custom effect: little music notes float up from a point on each note attack.

Use in the plan:
  {"type": "custom", "file": "rising_notes.py", "class": "RisingNotes",
   "at": [540, 1500], "from": 12, "to": 48, "spread": 160}

Pattern to copy:
  1. subclass Element, set kind / label / layer (and scale=0.5 for soft or full-frame effects)
  2. in __init__: read spec, get hits from ctx.music, precompute randomness with a seeded RNG,
     set self.start/self.end, and shrink the region with fit_region() when you can (faster)
  3. draw(t): start from self.blank(), draw in region-local coordinates, return the image
"""

import math
import random

from PIL import ImageDraw

from core.base import Element, clamp, ease_out, hex_rgb, mix, rgba


class RisingNotes(Element):
    kind = "rising_notes"
    layer = 20

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        u = ctx.u
        m = ctx.music
        self.hits = m.hits(spec.get("kind", "note"), spec.get("sync", "auto"), spec.get("from"), spec.get("to"))
        self.start, self.end = m.span(spec.get("from"), spec.get("to"))
        self.end = min(ctx.duration, self.end + 2.0)  # let the last notes finish floating
        ax, ay = spec.get("at") or [ctx.W / 2, ctx.H * 0.75]
        spread = float(spec.get("spread", 160)) * u
        self.rise = float(spec.get("rise", 360)) * u
        self.life = float(spec.get("life", 1.8))
        cols = [hex_rgb(c) for c in spec["colors"]] if spec.get("colors") else [ctx.accent, (255, 255, 255), mix(ctx.accent, (255, 255, 255), 0.5)]
        self.notes = []
        for i, (t, s) in enumerate(self.hits):
            rng = random.Random(i * 104729 + 7)
            self.notes.append((t, ax + rng.uniform(-spread, spread), ay, (18 + 14 * s) * u,
                               rng.choice(cols), rng.choice([1, 2]), rng.uniform(-1, 1)))
        pad = 60 * u
        self.fit_region(ax - spread - pad, ay - self.rise - pad, ax + spread + pad, ay + pad)
        self.label = "飘音符"
        self.times = [n[0] for n in self.notes]

    def preview_time(self):
        return self.times[len(self.times) // 2] + 0.5 if self.times else self.start

    def draw(self, t):
        im = self.blank()
        d = ImageDraw.Draw(im)
        u = self.ctx.u
        for bt, x, y, size, col, heads, sway in self.notes:
            lt = t - bt
            if lt < 0 or lt > self.life:
                continue
            p = lt / self.life
            k = min(ease_out(lt / 0.15), 1 - clamp((p - 0.6) / 0.4))
            cx = x + math.sin(lt * 3 + sway * 3) * 18 * u - self.x
            cy = y - self.rise * ease_out(p) - self.y
            r = size * 0.42
            c = rgba(col, 255 * k)
            stroke = max(2, int(size * 0.14))
            heads_x = [cx] if heads == 1 else [cx - size * 0.45, cx + size * 0.45]
            for hx in heads_x:
                d.ellipse([hx - r, cy - r * 0.75, hx + r, cy + r * 0.75], fill=c)
                d.line([hx + r - stroke / 2, cy, hx + r - stroke / 2, cy - size * 1.3], fill=c, width=stroke)
            if heads == 2:
                d.line([heads_x[0] + r - stroke / 2, cy - size * 1.3, heads_x[1] + r - stroke / 2, cy - size * 1.3], fill=c, width=stroke * 2)
            else:
                d.line([cx + r - stroke / 2, cy - size * 1.3, cx + r + size * 0.35, cy - size * 0.9], fill=c, width=stroke)
        return im

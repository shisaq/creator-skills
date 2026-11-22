"""Built-in MV accents. Each is a short, readable example of the Element + ctx.music pattern;
copy one into your own file to make something new (see references/custom.md)."""

from __future__ import annotations

import bisect
import math
import random

import numpy as np
from PIL import Image, ImageDraw

from core.base import Element, clamp, ease_out, ease_out_back, even, hex_rgb, mix, rgba


def _color(ctx, spec, key="color"):
    return hex_rgb(spec[key]) if spec.get(key) else ctx.accent


class Pulse(Element):
    """Glow around the frame edge that 'breathes' with the music.
    spec: from, to, sync, kind(beat|down|note), strength(0.3–1.5), decay(s), thickness(0–0.2 of short side), color"""

    kind = "pulse"
    layer = 10
    scale = 0.5

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        m = ctx.music
        self.hits = m.hits(spec.get("kind", "beat"), spec.get("sync", "auto"), spec.get("from"), spec.get("to"))
        self.start, self.end = m.span(spec.get("from"), spec.get("to"))
        self.gain = float(spec.get("strength", 1.0))
        self.decay = float(spec.get("decay", 0.22))
        self.label = "边框律动"
        W2, H2 = self.size
        th = float(spec.get("thickness", 0.075)) * min(W2, H2)
        yy, xx = np.mgrid[0:H2, 0:W2].astype(np.float32)
        dist = np.minimum(np.minimum(xx, W2 - 1 - xx), np.minimum(yy, H2 - 1 - yy))
        self.mask = np.clip(1 - dist / th, 0, 1) ** 2
        self.rgb = np.empty((H2, W2, 3), np.uint8)
        self.rgb[:] = _color(ctx, spec)

    def extra_sig(self):
        return [len(self.hits), self.hits[:3]]

    def level(self, t):
        m = self.ctx.music
        v = m.envelope(t, self.hits, self.decay) * (0.4 + 0.6 * m.energy(t)) * self.gain
        edge = min(ease_out((t - self.start) / 0.6), ease_out((self.end - t) / 0.6))
        return clamp(v) * edge

    def preview_time(self):
        if not self.hits:
            return self.start
        mid = len(self.hits) // 2
        return max(self.hits[max(0, mid - 6):mid + 6], key=lambda h: h[1])[0] + 0.02

    def draw(self, t):
        a = (self.mask * (215 * self.level(t))).astype(np.uint8)
        return Image.fromarray(np.dstack([self.rgb, a]), "RGBA")


class Sparkles(Element):
    """Star bursts on strong hits from fixed anchor points.
    spec: from, to, sync, kind(big|down|beat|note), anchors [[x,y],...], strength, colors ["#hex",...]"""

    kind = "sparkles"
    layer = 12
    scale = 0.5

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        m = ctx.music
        self.hits = m.hits(spec.get("kind", "big"), spec.get("sync", "auto"), spec.get("from"), spec.get("to"))
        self.start, self.end = m.span(spec.get("from"), spec.get("to"))
        self.end = min(ctx.duration, self.end + 1.0)
        W, H = ctx.W, ctx.H
        anchors = spec.get("anchors") or ([[0.12 * W, 0.2 * H], [0.88 * W, 0.2 * H]] if ctx.portrait
                                          else [[0.08 * W, 0.28 * H], [0.92 * W, 0.28 * H]])
        self.anchors = [(float(a[0]), float(a[1])) for a in anchors]
        self.label = "闪光粒子"
        gain = float(spec.get("strength", 1.0))
        pal = [hex_rgb(c) for c in spec["colors"]] if spec.get("colors") else \
            [ctx.accent, (255, 255, 255), mix(ctx.accent, (255, 255, 255), 0.55)]
        self.bursts = []
        for i, (t, s) in enumerate(self.hits):
            rng = random.Random(i * 7919 + 13)  # deterministic: same frames every render
            pts = self.anchors if (s >= 0.95 and len(self.anchors) > 1 and i % 4 == 0) else [self.anchors[i % len(self.anchors)]]
            parts = []
            for ax, ay in pts:
                for _ in range(int((12 + 10 * s) * gain)):
                    ang = rng.uniform(0, 2 * math.pi)
                    sp = rng.uniform(200, 560) * ctx.u
                    parts.append((ax, ay, math.cos(ang) * sp, math.sin(ang) * sp, rng.uniform(0.55, 1.0),
                                  rng.uniform(9, 20) * ctx.u, rng.choice(pal), rng.random() < 0.6, rng.uniform(0, 6.28)))
            self.bursts.append((t, parts))
        self.times = [b[0] for b in self.bursts]

    def extra_sig(self):
        return [len(self.hits), self.hits[:3]]

    def preview_time(self):
        return self.times[len(self.times) // 2] + 0.15 if self.times else self.start

    def draw(self, t):
        im = self.blank()
        d = ImageDraw.Draw(im)
        sc = self.scale
        i = bisect.bisect_right(self.times, t)
        j = bisect.bisect_left(self.times, t - 1.05)
        for bt, parts in self.bursts[j:i]:
            lt = t - bt
            for ax, ay, vx, vy, life, size, col, star, rot in parts:
                if lt > life:
                    continue
                p = lt / life
                drag = (1 - math.exp(-3 * lt)) / 3
                x = (ax + vx * drag) * sc
                y = (ay + vy * drag + 140 * self.ctx.u * lt * lt) * sc
                r = size * sc * (1 - 0.6 * p) * (0.6 + 0.4 * ease_out_back(min(1, lt / 0.12)))
                a = 255 * (1 - p) ** 1.3
                if star:
                    pts = [(x + r * (1.0 if k % 2 == 0 else 0.32) * math.cos(rot + lt * 4 + k * math.pi / 4),
                            y + r * (1.0 if k % 2 == 0 else 0.32) * math.sin(rot + lt * 4 + k * math.pi / 4)) for k in range(8)]
                    d.polygon(pts, fill=rgba(col, a))
                else:
                    d.ellipse([x - r * 0.45, y - r * 0.45, x + r * 0.45, y + r * 0.45], fill=rgba(col, a))
        return im


class SongCard(Element):
    """Lower-third with the song name and five little level bars that bounce with the music.
    spec: title, sub, start, dur, at [x,y] (top-left, optional)"""

    kind = "song_card"
    layer = 40

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        u = ctx.u
        self.title, self.sub = spec.get("title") or "", spec.get("sub") or ""
        self.start = float(spec.get("start", 0.8))
        self.end = min(ctx.duration, self.start + float(spec.get("dur", 6.0)))
        self.ft, self.fs = ctx.font("title", 52), ctx.font("ui", 24)
        tw = max(self.ft.getlength(self.title), self.fs.getlength(self.sub) if self.sub else 0)
        self.eq_w = 5 * 9 * u + 4 * 6 * u
        cw, ch = tw + self.eq_w + 100 * u, (130 if self.sub else 96) * u
        if spec.get("at"):
            x0, y0 = float(spec["at"][0]), float(spec["at"][1])
        else:
            x0 = 40 * u
            y0 = (0.66 * ctx.H) if ctx.portrait else (ctx.H - ch - 0.1 * ctx.H)
        self.fit_region(x0, y0, x0 + cw, y0 + ch)
        self.label = "歌名卡·" + self.title
        self.hits = ctx.music.hits("beat", "auto")

    def bar(self, t, i):
        tt = t - i * 0.045
        h = self.ctx.music.last_hit(tt, self.hits)
        if not h:
            return 0.3 + 0.2 * math.sin(tt * 5 + i)
        v = h[1] * math.exp(-(tt - h[0]) / (0.18 + 0.05 * i))
        return clamp(0.2 + 0.8 * v + 0.08 * math.sin(tt * 9 + i * 1.7))

    def draw(self, t):
        ctx, u = self.ctx, self.ctx.u
        im = self.blank()
        lt, dur = t - self.start, self.end - self.start
        reveal, k = ease_out(lt / 0.45), 1 - clamp((lt - (dur - 0.35)) / 0.35)
        if reveal <= 0 or k <= 0:
            return im
        d = ImageDraw.Draw(im)
        W, H = self.w, self.h
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(22 * u), fill=rgba(ctx.dark, 232 * k))
        d.rounded_rectangle([0, 0, 10 * u, H - 1], radius=int(5 * u), fill=rgba(ctx.accent, 255 * k))
        tx = 34 * u
        if self.sub:
            d.text((tx, 20 * u), self.title, font=self.ft, fill=rgba(ctx.light, 255 * k))
            d.text((tx, 82 * u), self.sub, font=self.fs, fill=rgba(ctx.accent, 255 * k))
        else:
            d.text((tx, H / 2), self.title, font=self.ft, fill=rgba(ctx.light, 255 * k), anchor="lm")
        bx, base, maxh = W - 40 * u - self.eq_w, H - 26 * u, H - 52 * u
        for i in range(5):
            hgt = max(6 * u, maxh * self.bar(t, i))
            x = bx + i * 15 * u
            d.rounded_rectangle([x, base - hgt, x + 9 * u, base], radius=int(4 * u), fill=rgba(ctx.accent, 255 * k))
        if reveal < 1:  # wipe in from the left
            a = np.asarray(im.getchannel("A")).copy()
            a[:, int(W * reveal):] = 0
            im.putalpha(Image.fromarray(a))
        return im


class EndCard(Element):
    """Last few seconds: dim the frame and pop a big line of text.
    spec: title, sub, dur, dim (true/false)"""

    kind = "end_card"
    layer = 90

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        self.title, self.sub = spec.get("title") or "谢谢观看", spec.get("sub") or ""
        self.end = ctx.duration
        self.start = max(0.0, self.end - float(spec.get("dur", 4.0)))
        self.dim = bool(spec.get("dim", True))
        self.label = "片尾卡·" + self.title
        self.fs = ctx.font("ui", 34)

    def preview_time(self):
        return min(self.end - 0.2, self.start + 1.5)

    def draw(self, t):
        ctx, u = self.ctx, self.ctx.u
        lt = t - self.start
        k = ease_out(lt / 0.5)
        im = Image.new("RGBA", (ctx.W, ctx.H), (0, 0, 0, int(140 * k) if self.dim else 0))
        d = ImageDraw.Draw(im)
        if lt > 0.15:
            s = 0.7 + 0.3 * ease_out_back((lt - 0.15) / 0.45)
            ft = ctx.font("title", (110 if not ctx.portrait else 96) * s)
            cy = ctx.H * 0.46
            d.text((ctx.W / 2, cy), self.title, font=ft, fill=rgba(ctx.accent, 255 * k), anchor="mm",
                   stroke_width=max(2, int(8 * u)), stroke_fill=rgba(ctx.dark, 255 * k))
            if self.sub:
                k2 = ease_out((lt - 0.45) / 0.4)
                pw, ph = self.fs.getlength(self.sub) + 50 * u, 66 * u
                y = cy + 95 * u
                d.rounded_rectangle([ctx.W / 2 - pw / 2, y, ctx.W / 2 + pw / 2, y + ph], radius=int(ph / 2),
                                    fill=rgba(ctx.dark, 235 * k2), outline=rgba(ctx.accent, 255 * k2), width=max(2, int(3 * u)))
                d.text((ctx.W / 2, y + ph / 2), self.sub, font=self.fs, fill=(255, 255, 255, int(255 * k2)), anchor="mm")
        return im


BUILTIN = {"pulse": Pulse, "sparkles": Sparkles, "song_card": SongCard, "end_card": EndCard}

"""Chapter bars. ChapterBase does the chapter maths; TabsBar and LineBar are two finished looks,
and also the reference for writing your own (see references/custom.md)."""

from __future__ import annotations

from PIL import Image, ImageDraw

from core.base import Ctx, Element, clamp, ease_out, ease_out_back, even, mix, rgba


class ChapterBase(Element):
    """spec: {"items": [{"start": s, "title": "..."}], "position": "top"|"bottom", "y": optional px}

    Gives subclasses:
      self.segs                [(start, end, title)]
      self.index_at(t)         current chapter index
      self.progress_in(t)      0..1 inside the current chapter
      self.x_of(time)          time → x pixel on a full-width bar
      self.changed_ago(t)      seconds since the current chapter began
    """

    kind = "chapters"
    layer = 30

    def __init__(self, ctx: Ctx, spec: dict, height_1080: float = 46):
        super().__init__(ctx, spec)
        items = sorted(spec["items"], key=lambda c: c["start"])
        D = ctx.duration
        self.segs = [(float(c["start"]), float(items[i + 1]["start"]) if i + 1 < len(items) else D, str(c["title"]))
                     for i, c in enumerate(items)]
        self.start, self.end = self.segs[0][0], D
        self.bh = even(height_1080 * ctx.u)
        pos = spec.get("position", "top")
        if spec.get("y") is not None:
            y = int(spec["y"])
        elif pos == "bottom":
            y = ctx.H - self.bh - (even(0.13 * ctx.H) if ctx.portrait else 0)
        else:
            y = even(0.06 * ctx.H) if ctx.portrait else 0
        self.position = pos
        self.bar_y = y
        self.x, self.y, self.w, self.h = 0, y, ctx.W, self.bh
        self.label = "章节条"
        for s, _, _ in self.segs[1:]:
            self.sfx.append((s - 0.12, "whoosh", 0.10))

    def index_at(self, t):
        for i, (s, e, _) in enumerate(self.segs):
            if s <= t < e:
                return i
        return len(self.segs) - 1

    def progress_in(self, t):
        s, e, _ = self.segs[self.index_at(t)]
        return clamp((t - s) / max(0.01, e - s))

    def changed_ago(self, t):
        return t - self.segs[self.index_at(t)][0]

    def x_of(self, time):
        return time / self.ctx.duration * self.ctx.W

    def preview_times(self):
        return [(s + 1.2, f"章节·{title}") for s, _, title in self.segs[:8]]


class TabsBar(ChapterBase):
    """Full-width dark bar, every chapter labelled; current one lit with a progress underline."""

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec, 56 if ctx.portrait else 46)
        u, D = ctx.u, ctx.duration
        base = 30 if ctx.portrait else 22
        gap = 3 * u
        need = base
        f = ctx.font("ui", base)
        for s, e, title in self.segs:
            segw = (e - s) / D * ctx.W - 2 * gap - 16 * u
            tw = f.getlength(title)
            if tw > segw and tw > 0:
                need = min(need, base * segw / tw)
        self.fs = max(base * (0.9 if ctx.portrait else 0.78), need)
        self.font = ctx.font("ui", self.fs)
        self.pill_font = ctx.font("ui", base)
        self.show = [self.font.getlength(t) <= (e - s) / D * ctx.W - 2 * gap - 12 * u for s, e, t in self.segs]

    def draw(self, t):
        ctx, u = self.ctx, self.ctx.u
        W, bh = ctx.W, self.bh
        im = Image.new("RGBA", (W, bh), rgba(mix(ctx.dark, (0, 0, 0), 0.2), 235))
        d = ImageDraw.Draw(im)
        gap, line = 3 * u, max(4, even(5 * u))
        cur_i = self.index_at(t)
        for i, (s, e, title) in enumerate(self.segs):
            x0, x1 = self.x_of(s) + gap, self.x_of(e) - gap
            cur, done = i == cur_i, i < cur_i
            if cur:
                d.rectangle([x0, 0, x1, bh], fill=rgba(mix(ctx.dark, ctx.accent, 0.28), 255))
                d.rectangle([x0, bh - line, x0 + (x1 - x0) * self.progress_in(t), bh], fill=rgba(ctx.accent, 255))
            elif done:
                d.rectangle([x0, bh - line, x1, bh], fill=rgba(mix(ctx.accent, ctx.dark, 0.35), 255))
            else:
                d.rectangle([x0, bh - line, x1, bh], fill=(90, 86, 82, 255))
            col = rgba(mix(ctx.accent, (255, 255, 255), 0.3), 255) if cur else ((235, 232, 226, 255) if done else (160, 156, 150, 255))
            if self.show[i]:
                d.text(((x0 + x1) / 2, (bh - line) / 2 + 1), title, font=self.font, fill=col, anchor="mm")
        if not self.show[cur_i]:  # too narrow for its label: show the current one as a pill
            s, e, title = self.segs[cur_i]
            pw = self.pill_font.getlength(title) + 28 * u
            cx = clamp((self.x_of(s) + self.x_of(e)) / 2, pw / 2 + 2, W - pw / 2 - 2)
            d.rounded_rectangle([cx - pw / 2, 3 * u, cx + pw / 2, bh - line - 3 * u], radius=int(bh / 2), fill=rgba(ctx.accent, 255))
            d.text((cx, (bh - line) / 2 + 1), title, font=self.pill_font, fill=rgba(ctx.dark, 255), anchor="mm")
        return im


class LineBar(ChapterBase):
    """Minimal: a thin segmented progress line; the chapter name floats in as a chip for a few seconds after each change."""

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec, 8)
        u = ctx.u
        self.lh = max(4, even(6 * u))
        self.chip_font = ctx.font("ui", 26 if not ctx.portrait else 32)
        self.num_font = ctx.font("title", 26 if not ctx.portrait else 32)
        self.chip_secs = float(spec.get("chip_secs", 3.5))
        chip_h = even(52 * u)
        # region: line + room for the chip
        if self.position == "bottom":
            self.fit_region(0, self.bar_y + self.bh - self.lh - chip_h - 18 * u, ctx.W, self.bar_y + self.bh)
        else:
            self.fit_region(0, self.bar_y, ctx.W, self.bar_y + self.lh + chip_h + 18 * u)
        self.chip_h = chip_h

    def draw(self, t):
        ctx, u = self.ctx, self.ctx.u
        im = self.blank()
        d = ImageDraw.Draw(im)
        W, lh = ctx.W, self.lh
        ly = (self.h - lh) if self.position == "bottom" else 0
        gap = 3 * u
        cur_i = self.index_at(t)
        d.rectangle([0, ly, W, ly + lh], fill=(0, 0, 0, 90))
        for i, (s, e, _) in enumerate(self.segs):
            x0, x1 = self.x_of(s) + (gap if i else 0), self.x_of(e) - gap
            if i < cur_i:
                d.rectangle([x0, ly, x1, ly + lh], fill=rgba(ctx.accent, 235))
            elif i == cur_i:
                d.rectangle([x0, ly, x1, ly + lh], fill=(255, 255, 255, 70))
                d.rectangle([x0, ly, x0 + (x1 - x0) * self.progress_in(t), ly + lh], fill=rgba(ctx.accent, 255))
            else:
                d.rectangle([x0, ly, x1, ly + lh], fill=(255, 255, 255, 70))
        ago = self.changed_ago(t)
        if self.chip_secs > 0 and ago < self.chip_secs:
            k = min(ease_out(ago / 0.35), 1 - clamp((ago - (self.chip_secs - 0.4)) / 0.4))
            s, e, title = self.segs[cur_i]
            num = f"{cur_i + 1:02d}"
            nw = self.num_font.getlength(num)
            tw = self.chip_font.getlength(title)
            pw, ph = nw + tw + 50 * u, self.chip_h
            cx = clamp(self.x_of(s) + pw / 2, pw / 2 + 12 * u, W - pw / 2 - 12 * u)
            slide = (1 - ease_out_back(min(1, ago / 0.45))) * 14 * u
            if self.position == "bottom":
                cy = ly - 10 * u - ph / 2 + slide
            else:
                cy = ly + lh + 10 * u + ph / 2 - slide
            d.rounded_rectangle([cx - pw / 2, cy - ph / 2, cx + pw / 2, cy + ph / 2], radius=int(ph / 2),
                                fill=rgba(ctx.dark, 225 * k))
            x = cx - pw / 2 + 20 * u
            d.text((x, cy), num, font=self.num_font, fill=rgba(ctx.accent, 255 * k), anchor="lm")
            d.text((x + nw + 10 * u, cy), title, font=self.chip_font, fill=rgba((255, 255, 255), 255 * k), anchor="lm")
        return im


class Announce(Element):
    """Optional big chapter title card at each chapter start ("02 调速度"), for longer tutorials."""

    kind = "announce"
    layer = 60

    def __init__(self, ctx, spec, index, start, title, dur=2.2):
        super().__init__(ctx, {"i": index, "title": title, "start": start, "dur": dur})
        self.start, self.end = start, min(ctx.duration, start + dur)
        self.num, self.title = f"{index + 1:02d}", title
        self.fn = ctx.font("title", 64)
        self.ft = ctx.font("title", 92 if not ctx.portrait else 80)
        tw = max(self.fn.getlength(self.num), self.ft.getlength(title))
        u = ctx.u
        w, h = tw + 120 * u, 230 * u
        cx, cy = ctx.W / 2, ctx.H * (0.42 if ctx.portrait else 0.45)
        self.fit_region(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        self.label = f"章节卡·{title}"
        self.sfx.append((start, "pop", 0.16))

    def draw(self, t):
        ctx, u = self.ctx, self.ctx.u
        lt, dur = t - self.start, self.end - self.start
        k = min(ease_out(lt / 0.3), 1 - clamp((lt - (dur - 0.35)) / 0.35))
        im = self.blank()
        d = ImageDraw.Draw(im)
        cx = self.w / 2
        rise = (1 - ease_out(lt / 0.45)) * 20 * u
        d.text((cx, self.h * 0.30 + rise), self.num, font=self.fn, fill=rgba(ctx.accent, 255 * k), anchor="mm",
               stroke_width=max(2, int(5 * u)), stroke_fill=rgba(ctx.dark, 255 * k))
        d.text((cx, self.h * 0.66 + rise), self.title, font=self.ft, fill=rgba((255, 255, 255), 255 * k), anchor="mm",
               stroke_width=max(2, int(7 * u)), stroke_fill=rgba(ctx.dark, 255 * k))
        return im


STYLES = {"tabs": TabsBar, "line": LineBar}


def build(ctx: Ctx, plan: dict) -> list[Element]:
    bar = plan.get("bar") or {}
    items = plan.get("chapters") or []
    els: list[Element] = []
    style = bar.get("style", "tabs")
    if items and style != "none":
        if style not in STYLES:
            raise SystemExit(f"bar.style 只能是 {', '.join(STYLES)} 或 none（用自定义样式时）。")
        els.append(STYLES[style](ctx, {**bar, "items": items}))
    if items and bar.get("announce"):
        srt = sorted(items, key=lambda c: c["start"])
        for i, c in enumerate(srt):
            if i == 0 and c["start"] < 1:
                continue
            els.append(Announce(ctx, {}, i, float(c["start"]), str(c["title"])))
    return els

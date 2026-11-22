"""Tools that let a vision-capable model *look* at the footage: contact sheets, coordinate grids, colour palette."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from . import fonts, media


def _font(size):
    try:
        return fonts.get("ui", size)
    except SystemExit:
        from PIL import ImageFont
        return ImageFont.load_default()


def contact_sheet(video: Path, meta: dict, times: list[float], out: Path, cols: int = 4, tile_w: int | None = None):
    """Frames at the given times with a timestamp on each — for understanding what happens when."""
    W, H = meta["width"], meta["height"]
    tw = tile_w or (420 if W >= H else 240)
    th = int(tw * H / W)
    rows = math.ceil(len(times) / cols)
    cap = 26
    img = Image.new("RGB", (cols * tw, rows * (th + cap)), (18, 18, 18))
    d = ImageDraw.Draw(img)
    f = _font(17)
    for i, t in enumerate(times):
        x, y = (i % cols) * tw, (i // cols) * (th + cap)
        img.paste(media.frame(video, t, tw, th), (x, y))
        d.text((x + 6, y + th + 4), media.fmt_time(t) + f"  ({t:.1f}s)", font=f, fill=(235, 235, 235))
    img.save(out, quality=85)
    return out


def grid_frame(video: Path, meta: dict, t: float, out: Path, step: float = 0.1):
    """One frame with a labelled pixel grid (every 10% by default) so a model can read off coordinates."""
    W, H = meta["width"], meta["height"]
    scale = min(1.0, 1600 / max(W, H))
    w, h = int(W * scale), int(H * scale)
    im = media.frame(video, t, w, h).convert("RGBA")
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    f = _font(14)
    n = int(round(1 / step))
    for i in range(1, n):
        x = int(w * i / n)
        y = int(h * i / n)
        for (a, b) in (((x, 0), (x, h)), ((0, y), (w, y))):
            d.line([a, b], fill=(0, 0, 0, 110), width=3)
            d.line([a, b], fill=(255, 255, 0, 170), width=1)
        lx, ly = int(W * i / n), int(H * i / n)
        for (px, py, txt) in ((x + 3, 3, str(lx)), (3, y + 2, str(ly))):
            tb = d.textbbox((px, py), txt, font=f)
            d.rectangle([tb[0] - 2, tb[1] - 1, tb[2] + 2, tb[3] + 1], fill=(0, 0, 0, 170))
            d.text((px, py), txt, font=f, fill=(255, 255, 0, 255))
    d.text((w - 6, h - 6), f"{media.fmt_time(t)}  原视频 {W}x{H}，格线上的数字是原视频像素", font=f,
           fill=(255, 255, 255, 230), anchor="rd", stroke_width=2, stroke_fill=(0, 0, 0, 200))
    Image.alpha_composite(im, lay).convert("RGB").save(out, quality=88)
    return out


def palette(video: Path, meta: dict, times: list[float], k: int = 6) -> list[tuple[str, float]]:
    """Dominant colours across a few frames: [(#hex, share)], most common first."""
    tiles = [media.frame(video, t, 160, max(1, int(160 * meta["height"] / meta["width"]))) for t in times]
    w = sum(t.width for t in tiles)
    strip = Image.new("RGB", (w, max(t.height for t in tiles)))
    x = 0
    for t in tiles:
        strip.paste(t, (x, 0))
        x += t.width
    q = strip.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: 3 * k]
    counts = sorted(q.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)
    out = []
    for c, idx in counts:
        r, g, b = pal[3 * idx: 3 * idx + 3]
        out.append((f"#{r:02X}{g:02X}{b:02X}", round(c / total, 3)))
    return out


def describe_palette(pal) -> str:
    def lum(hx):
        r, g, b = (int(hx[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def sat(hx):
        r, g, b = (int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5))
        mx, mn = max(r, g, b), min(r, g, b)
        return 0 if mx == 0 else (mx - mn) / mx

    lines = []
    for hx, share in pal:
        tone = "亮" if lum(hx) > 170 else ("暗" if lum(hx) < 70 else "中")
        s = sat(hx)
        lines.append(f"{hx}  {share:.0%}  {tone}{'、鲜艳' if s > 0.45 else ('、灰' if s < 0.15 else '')}")
    avg = sum(lum(h) * s for h, s in pal)
    lines.append(f"画面整体偏{'亮' if avg > 150 else ('暗' if avg < 90 else '中等亮度')}。")
    return "\n".join(lines)

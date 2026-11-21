#!/usr/bin/env python3
"""Build the HyperFrames packaging project from a spec (see references/spec.md).

    python3 build.py spec.json [--project DIR]

Reads the refined cut, its face track and captions, and writes a HyperFrames project:
index.html (footage + PiP camera + music/sfx) and one sub-composition per card, plus captions.
Then: python3 hf.py check|snap|render <project>.

Layout rules baked in (from real reviews, keep them):
  - full-frame sections stay clean: only captions, plus the hook title and the closing line;
  - captions sit below the lowest chin of their section, never over the mouth;
  - the PiP window follows the face (smoothed), it is never a fixed crop;
  - one punch-in at most per emphasis, no alternating zooms.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 1080, 1920
BOX = (740, 300, 280, 340)          # PiP capsule on screen: x, y, w, h
CROP_W = 800                        # source px across the capsule
CAP_PIP_TOP = 1268                  # caption top while the PiP layout is on screen


# --------------------------------------------------------------------------- helpers

def die(msg):
    raise SystemExit(msg)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def ffmpeg():
    f = shutil.which("ffmpeg")
    if not f:
        die("ffmpeg not found.")
    return f


def probe_duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def esc(s):
    return html.escape(str(s), quote=True)


MARK = re.compile(r"\{([a-z,]+):([^{}]+)\}")


def rich(s: str) -> str:
    """'逼走{a:黄仁勋}' → coloured spans. Keys: a, b, accent, muted; u = underline. Combine: {accent,u:…}. \\n = line break."""
    out, last = "", 0
    for m in MARK.finditer(s):
        out += esc(s[last:m.start()])
        keys = m.group(1).split(",")
        cls = " ".join({"a": "ca", "b": "cb", "accent": "cy", "muted": "cm", "u": "ul"}.get(k, "") for k in keys)
        out += f'<span class="{cls}">{esc(m.group(2))}</span>'
        last = m.end()
    return (out + esc(s[last:])).replace("\n", "<br>")


# --------------------------------------------------------------------------- fonts

FONT_CANDIDATES = {
    "heavy": ["Alibaba-PuHuiTi-Heavy.ttf", "AlibabaPuHuiTi-3-105-Heavy.ttf", "SourceHanSansSC-Heavy.otf",
              "NotoSansSC-Black.ttf", "NotoSansCJKsc-Black.otf"],
    "bold": ["Alibaba-PuHuiTi-Bold.ttf", "AlibabaPuHuiTi-3-85-Bold.ttf", "SourceHanSansSC-Bold.otf",
             "NotoSansSC-Bold.ttf", "NotoSansCJKsc-Bold.otf"],
    "medium": ["Alibaba-PuHuiTi-Medium.ttf", "AlibabaPuHuiTi-3-65-Medium.ttf", "SourceHanSansSC-Medium.otf",
               "NotoSansSC-Medium.ttf", "NotoSansCJKsc-Medium.otf"],
}
FONT_DIRS = [Path.home() / "Library/Fonts", Path("/Library/Fonts"), Path.home() / ".local/share/fonts",
             Path("/usr/share/fonts"), Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts"]
NOTO = "https://cdn.jsdelivr.net/fontsource/fonts/noto-sans-sc@latest/chinese-simplified-{w}-normal.woff2"


def find_fonts(spec_fonts: dict | None, dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    got = {}
    for role in ("heavy", "bold", "medium"):
        src = None
        if spec_fonts and spec_fonts.get(role):
            src = Path(spec_fonts[role]).expanduser()
        else:
            for name in FONT_CANDIDATES[role]:
                for d in FONT_DIRS:
                    hits = list(d.rglob(name)) if d.is_dir() else []
                    if hits:
                        src = hits[0]
                        break
                if src:
                    break
        if src and src.is_file():
            target = dest / f"{role}{src.suffix.lower()}"
            shutil.copy2(src, target)
            got[role] = target.name
            continue
        cache = Path.home() / ".cache/creator-skills/fonts"
        cache.mkdir(parents=True, exist_ok=True)
        w = {"heavy": 900, "bold": 700, "medium": 500}[role]
        f = cache / f"noto-sans-sc-{w}.woff2"
        if not f.exists():
            import urllib.request
            print(f"Downloading Noto Sans SC {w} ...", flush=True)
            urllib.request.urlretrieve(NOTO.format(w=w), f)
        shutil.copy2(f, dest / f"{role}.woff2")
        got[role] = f"{role}.woff2"
    return got


def font_css(fonts):
    w = {"heavy": 900, "bold": 700, "medium": 500}
    return "".join(f"@font-face{{font-family:'Display';src:url('assets/fonts/{fn}');font-weight:{w[r]};}}"
                   for r, fn in fonts.items())


# --------------------------------------------------------------------------- face track

class Face:
    def __init__(self, path: Path | None):
        self.s = []
        if path and path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            self.s = [x for x in d["samples"] if x[1] is not None]

    def at(self, t, win=0.6):
        if not self.s:
            return (540, 900, 640, 640)
        pts = [x for x in self.s if abs(x[0] - t) <= win] or [min(self.s, key=lambda x: abs(x[0] - t))]
        n = len(pts)
        return tuple(sum(p[i] for p in pts) / n for i in (1, 2, 3, 4))

    def chin(self, a, b):
        pts = [x for x in self.s if a <= x[0] < b] or self.s
        return max(x[2] + x[4] for x in pts) + 70 if pts else 1330

    def crop(self, t):
        x, y, w, h = self.at(t)
        cw = CROP_W
        ch = cw * BOX[3] / BOX[2]
        cx = min(max(x + w / 2, cw / 2), W - cw / 2)
        cy = min(max(y + h / 2 + 40, ch / 2), H - ch / 2)
        L, T = cx - cw / 2, cy - ch / 2
        R, B = W - (cx + cw / 2), H - (cy + ch / 2)
        s = BOX[2] / cw
        rad = (BOX[2] / 2) / s
        return (f'x:{BOX[0] - L * s:.2f},y:{BOX[1] - T * s:.2f},scale:{s:.4f},'
                f'clipPath:"inset({T:.0f}px {R:.0f}px {B:.0f}px {L:.0f}px round {rad:.0f}px)"')


FULL = 'x:0,y:0,scale:1,clipPath:"inset(0px 0px 0px 0px round 0px)"'


# --------------------------------------------------------------------------- scene files

BASE_CSS = """
#root{position:absolute;inset:0;font-family:'Display',sans-serif;color:#fff;}
.ca{color:var(--a)}.cb{color:var(--b)}.cy{color:var(--accent)}.cm{color:#9FB4D9}
.ul{display:inline-block;border-bottom:8px solid var(--accent);padding-bottom:2px}
.tag{position:absolute;left:100px;top:300px;display:inline-block;padding:6px 22px;border:3px solid var(--accent);border-radius:40px;color:var(--accent);font-weight:700;font-size:32px;line-height:1.2;background:rgba(10,15,26,.55)}
.ttl{position:absolute;left:100px;font-weight:900;line-height:1.18;letter-spacing:1px;text-shadow:0 4px 18px rgba(0,0,0,.45)}
.note{position:absolute;left:100px;font-size:28px;font-weight:500;color:rgba(255,255,255,.6);line-height:1.4}
.card{position:absolute;left:60px;width:960px;border-radius:18px;overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.5)}
.row{position:absolute;left:60px;width:960px;border-radius:14px;background:rgba(18,30,56,.92);border:2px solid rgba(255,255,255,.08);border-left:8px solid var(--accent);display:flex;align-items:center;gap:28px;padding:0 22px;box-shadow:0 10px 30px rgba(0,0,0,.35)}
.scrim{position:absolute;left:0;top:0;width:1080px;background:linear-gradient(rgba(5,8,16,.8),rgba(5,8,16,.5) 60%,rgba(5,8,16,0))}
"""

JS_HEAD = """const tl = gsap.timeline({ paused: true });
const IN = (sel, t, from) => tl.fromTo(sel, Object.assign({opacity:0, y:40}, from||{}), {opacity:1, x:0, y:0, scale:1, duration:0.4, ease:"power3.out"}, t);
const OUT = (sel, t) => tl.to(sel, {opacity:0, duration:0.3, ease:"power2.in"}, t);
"""


class Scene:
    def __init__(self, cid, start, end, css_vars, fonts_css):
        self.cid, self.start, self.end = cid, start, end
        self.body, self.js, self.ids = [], [], []
        self.vars, self.fonts = css_vars, fonts_css

    def el(self, html_):
        self.body.append(html_)

    def t(self, abs_t):
        return round(max(0.0, abs_t - self.start), 2)

    def write(self, proj: Path):
        doc = f"""<template>
<style>{self.fonts}:root{{{self.vars}}}{BASE_CSS}</style>
<div id="root" data-composition-id="{self.cid}" data-width="{W}" data-height="{H}">
{chr(10).join(self.body)}
</div>
<script>
{JS_HEAD}{chr(10).join(self.js)}
window.__timelines["{self.cid}"] = tl;
</script>
</template>
"""
        (proj / "compositions" / f"{self.cid}.html").write_text(doc, encoding="utf-8")


def header(sc: Scene, card: dict, p: str):
    ids = []
    if card.get("tag"):
        sc.el(f'<div id="{p}-tag" class="tag">{rich(card["tag"])}</div>')
        ids.append(f"#{p}-tag")
    title = card.get("title") or []
    size = card.get("title_size", 74 if max((len(MARK.sub(r"\2", x)) for x in title), default=0) <= 7 else 60)
    y = 372
    for i, line in enumerate(title):
        sc.el(f'<div id="{p}-t{i}" class="ttl" style="top:{y}px;font-size:{size}px;width:620px">{rich(line)}</div>')
        ids.append(f"#{p}-t{i}")
        y += int(size * 1.25)
    if card.get("note"):
        sc.el(f'<div id="{p}-note" class="note" style="top:{max(y + 10, 560)}px;width:620px">{rich(card["note"])}</div>')
        ids.append(f"#{p}-note")
    t0 = sc.t(card["start"]) + 0.1
    for k, i in enumerate(ids):
        sc.js.append(f'IN("{i}",{t0 + 0.1 * k:.2f});')
    return ids


# ---- card bodies. Each returns the ids it created (for the shared exit).

def card_news(sc, c, p, assets):
    logo = f'<img src="{assets(c["logo"])}" style="height:30px">' if c.get("logo") else \
        f'<b style="font-size:30px">{esc(c.get("outlet", ""))}</b>'
    icons = ('<div style="display:flex;gap:28px;align-items:center;opacity:.9">'
             '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2"><circle cx="10.5" cy="10.5" r="7"/><path d="M16 16l6 6"/></svg>'
             '<svg width="28" height="22" viewBox="0 0 28 22" fill="#fff"><rect y="0" width="28" height="3"/><rect y="6" width="28" height="3"/><rect y="12" width="28" height="3"/><rect y="18" width="28" height="3"/></svg></div>')
    sc.el(f'''<div id="{p}-card" class="card" style="top:660px;background:{c.get("color", "#0A8935")}">
<div style="height:70px;background:{c.get("bar", "#212623")};display:flex;align-items:center;justify-content:space-between;padding:0 26px">{logo}{icons}</div>
<div style="padding:26px 34px 34px">
{f'<div style="width:30px;height:2px;background:rgba(255,255,255,.5);margin-bottom:10px"></div><div style="font-size:30px;font-weight:500">{esc(c["category"])}</div>' if c.get("category") else ""}
<div style="margin-top:22px;font-size:{c.get("size", 54)}px;font-weight:700;line-height:1.28">{"<br>".join(rich(x) for x in (c["headline"] if isinstance(c["headline"], list) else [c["headline"]]))}</div>
{f'<div style="margin-top:34px;font-size:28px;font-weight:700">{rich(c["byline"])}</div>' if c.get("byline") else ""}
</div></div>''')
    sc.js.append(f'IN("#{p}-card",{sc.t(c["start"]) + 0.35:.2f},{{y:80}});')
    return [f"#{p}-card"]


VERIFIED = {"gold": "#E2B719", "blue": "#1D9BF0", "grey": "#829AAB"}
X_LOGO = '<svg width="40" height="40" viewBox="0 0 24 24"><path fill="#0f1419" d="M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.41l-5.8-7.58-6.64 7.58H.47l8.6-9.83L0 1.15h7.6l5.24 6.93 6.06-6.93Zm-1.29 19.5h2.04L6.48 3.24H4.3l13.31 17.41Z"/></svg>'


def card_post(sc, c, p, assets):
    badge = ""
    if c.get("verified"):
        col = VERIFIED.get(c["verified"], c["verified"])
        badge = (f'<svg width="30" height="30" viewBox="0 0 24 24"><path fill="{col}" d="M22.25 12c0-1.43-.88-2.67-2.19-3.34.46-1.39.2-2.9-.81-3.91s-2.52-1.27-3.91-.81c-.66-1.31-1.91-2.19-3.34-2.19s-2.67.88-3.33 2.19c-1.4-.46-2.91-.2-3.92.81s-1.26 2.52-.8 3.91c-1.31.67-2.2 1.91-2.2 3.34s.89 2.67 2.2 3.34c-.46 1.39-.21 2.9.8 3.91s2.52 1.26 3.91.81c.67 1.31 1.91 2.19 3.34 2.19s2.68-.88 3.34-2.19c1.39.45 2.9.2 3.91-.81s1.27-2.52.81-3.91c1.31-.67 2.19-1.91 2.19-3.34z"/>'
                 '<path fill="#fff" d="M10.54 16.2l-3.6-3.6 1.42-1.41 2.18 2.17 5.13-5.13 1.42 1.41z"/></svg>')
    avatar = (f'<img src="{assets(c["avatar"])}" style="width:78px;height:78px;border-radius:{c.get("avatar_radius", "50%")};object-fit:cover">'
              if c.get("avatar") else '<div style="width:78px;height:78px;border-radius:50%;background:#cfd9de"></div>')
    paras = "".join(f'<p style="margin-top:{0 if i == 0 else 14}px">{rich(x)}</p>' for i, x in enumerate(c["paragraphs"]))
    stat = lambda icon, txt: f'<span style="display:flex;gap:10px;align-items:center">{icon}{esc(txt)}</span>'  # noqa: E731
    heart = '<svg width="28" height="28" viewBox="0 0 24 24"><path fill="#F91880" d="M12 21.6 10.6 20.3C5.4 15.6 2 12.5 2 8.7 2 5.6 4.4 3.2 7.5 3.2c1.7 0 3.4.8 4.5 2.1 1.1-1.3 2.8-2.1 4.5-2.1 3.1 0 5.5 2.4 5.5 5.5 0 3.8-3.4 6.9-8.6 11.6z"/></svg>'
    reply = '<svg width="28" height="28" viewBox="0 0 24 24"><path fill="#1D9BF0" d="M12 3C6.5 3 2 6.9 2 11.7c0 2.4 1.1 4.6 3 6.2L4.2 21.5l4.3-2.1c1.1.3 2.3.5 3.5.5 5.5 0 10-3.9 10-8.7S17.5 3 12 3z"/></svg>'
    link = '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#536471" stroke-width="2.2"><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>'
    footer = "".join([stat(heart, c.get("likes", "")) if c.get("likes") else "", stat(reply, c.get("reply_label", "回复")),
                      stat(link, c.get("link_label", "复制帖子链接"))])
    sc.el(f'''<div id="{p}-card" class="card" style="top:652px;background:#fff;color:#0f1419;border:1px solid #cfd9de;padding:30px 32px 22px">
<div style="display:flex;align-items:center;gap:18px">{avatar}
<div style="flex:1"><div style="font-size:32px;font-weight:700;display:flex;align-items:center;gap:8px">{esc(c["name"])} {badge}</div>
<div style="font-size:28px;color:#536471;font-weight:500">{esc(c.get("handle", ""))}{' · <span style="color:#006fd6;font-weight:700">关注</span>' if c.get("follow", True) else ""}</div></div>
<div style="align-self:flex-start">{X_LOGO if c.get("platform", "x") == "x" else ""}</div></div>
<div style="margin-top:18px;font-size:{c.get("size", 31)}px;line-height:1.45;font-weight:500">{paras}</div>
{f'<div style="margin-top:16px;font-size:28px;color:#536471;font-weight:500">{esc(c["time"])}</div>' if c.get("time") else ""}
<div style="margin-top:14px;padding-top:14px;border-top:1px solid #cfd9de;display:flex;gap:44px;font-size:28px;font-weight:700;color:#536471;align-items:center">{footer}</div>
</div>''')
    sc.js.append(f'IN("#{p}-card",{sc.t(c["start"]) + 0.35:.2f},{{y:80}});')
    return [f"#{p}-card"]


def card_pair(sc, c, p, assets, pal):
    ids = []
    people = c["people"][:2]
    enter = c.get("enter") or [c["start"] + 1.0, c["start"] + 1.6]
    for i, person in enumerate(people):
        x = 60 if i == 0 else 555
        col = pal.get(person.get("color", "a"), person.get("color"))
        sc.el(f'''<div id="{p}-p{i}" style="position:absolute;left:{x}px;top:668px;width:465px;height:480px;border-radius:18px;overflow:hidden;background:#121E38;border:2px solid rgba(255,255,255,.1);box-shadow:0 18px 50px rgba(0,0,0,.5)">
<img src="{assets(person["img"])}" style="width:465px;height:300px;object-fit:cover;object-position:{person.get("focus", "50% 18%")};display:block">
<div style="padding:16px 24px 0;font-size:42px;font-weight:900;color:{col}">{esc(person["name"])}</div>
{f'<div style="padding:4px 24px 0;font-size:28px;font-weight:500;color:rgba(255,255,255,.55)">{esc(c["label"])}</div>' if c.get("label") else ""}
<div style="position:relative;height:66px;margin:2px 24px 0;font-weight:900;font-size:56px;letter-spacing:2px">
<div class="{p}-p{i}-q" style="position:absolute;left:0;top:0">{esc(c.get("hidden", "????"))}</div>
<div class="{p}-p{i}-d" style="position:absolute;left:0;top:0;opacity:0;color:var(--accent)">{esc(person.get("value", c.get("value", "")))}</div></div></div>''')
        ids.append(f"#{p}-p{i}")
        sc.js.append(f'IN("#{p}-p{i}",{sc.t(enter[min(i, len(enter) - 1)]):.2f},{{x:{-80 if i == 0 else 80},y:0}});')
        if c.get("reveal") is not None:
            rt = sc.t(c["reveal"]) + 0.25 * i
            sc.js.append(f'tl.to(".{p}-p{i}-q",{{opacity:0,y:-30,duration:0.18}},{rt:.2f}); '
                         f'tl.fromTo(".{p}-p{i}-d",{{opacity:0,y:30}},{{opacity:1,y:0,duration:0.22,ease:"back.out(2)"}},{rt + 0.08:.2f});')
    if c.get("stamp"):
        st = c["stamp"]
        sc.el(f'<div id="{p}-stamp" style="position:absolute;left:0;top:880px;width:1080px;text-align:center"><span style="display:inline-block;padding:10px 40px;border:7px solid var(--b);border-radius:16px;color:var(--b);font-size:60px;font-weight:900;background:rgba(10,15,26,.82);letter-spacing:4px">{esc(st["text"])}</span></div>')
        sc.js.append(f'tl.fromTo("#{p}-stamp",{{opacity:0,scale:2.2,rotation:-14}},{{opacity:1,scale:1,rotation:-8,duration:0.28,ease:"power4.in"}},{sc.t(st["at"]):.2f});')
        ids.append(f"#{p}-stamp")
    return ids


def card_rows(sc, c, p, assets, pal):
    ids = []
    rows = c["rows"]
    hgt = 150 if len(rows) <= 3 else 118
    for i, r in enumerate(rows):
        col = pal.get(r.get("color", ""), r.get("color") or "#fff")
        img = (f'<img src="{assets(r["img"])}" style="width:{hgt - 38}px;height:{hgt - 38}px;border-radius:50%;object-fit:cover;object-position:{r.get("focus", "50% 20%")}">'
               if r.get("img") else "")
        sc.el(f'''<div id="{p}-r{i}" class="row" style="top:{660 + i * (hgt + 20)}px;height:{hgt}px;border-left-color:{col}">{img}
<div><div style="font-size:44px;font-weight:900;line-height:1.2;color:{col}">{esc(r["name"])}</div>
<div style="font-size:34px;font-weight:500;color:rgba(255,255,255,.85)">{rich(r.get("text", ""))}</div></div></div>''')
        sc.js.append(f'IN("#{p}-r{i}",{sc.t(r.get("at", c["start"] + 1 + i)):.2f},{{x:-60,y:0}});')
        ids.append(f"#{p}-r{i}")
    return ids


def card_timeline(sc, c, p, assets, pal):
    ids = []
    nodes = c["nodes"]
    gap = min(68, 480 // max(1, len(nodes)))
    sc.el(f'<div id="{p}-line" style="position:absolute;left:295px;top:690px;width:4px;height:{gap * (len(nodes) - 1)}px;background:rgba(255,255,255,.18);transform-origin:top"></div>')
    ids.append(f"#{p}-line")
    if nodes:
        sc.js.append(f'tl.fromTo("#{p}-line",{{scaleY:0}},{{scaleY:1,duration:{max(0.3, nodes[-1]["at"] - nodes[0]["at"]):.2f},ease:"none"}},{sc.t(nodes[0]["at"]):.2f});')
    for i, n in enumerate(nodes):
        col = pal.get(n.get("color", ""), n.get("color") or "#9FB4D9")
        strong = bool(n.get("color"))
        sc.el(f'''<div id="{p}-n{i}" style="position:absolute;left:90px;top:{668 + i * gap}px;width:960px;height:60px;display:flex;align-items:center">
<div style="width:180px;text-align:right;font-size:34px;font-weight:900;color:rgba(255,255,255,.7)">{esc(n["when"])}</div>
<div style="width:22px;height:22px;border-radius:11px;margin:0 30px 0 16px;background:{col};box-shadow:0 0 0 6px rgba(255,255,255,.08)"></div>
<div style="font-size:44px;font-weight:{900 if strong else 700};color:{col if strong else "#fff"}">{rich(n["text"])}</div></div>''')
        sc.js.append(f'IN("#{p}-n{i}",{sc.t(n["at"]):.2f},{{x:-40,y:0}});')
        ids.append(f"#{p}-n{i}")
    return ids


def card_image(sc, c, p, assets, pal):
    sc.el(f'<div id="{p}-card" class="card" style="top:660px;max-height:490px;background:{c.get("bg", "#fff")}">'
          f'<img src="{assets(c["src"])}" style="width:960px;display:block"></div>')
    sc.js.append(f'IN("#{p}-card",{sc.t(c.get("at", c["start"]) ) + 0.35:.2f},{{y:80}});')
    return [f"#{p}-card"]


CARDS = {"news": lambda sc, c, p, a, pal: card_news(sc, c, p, a), "post": lambda sc, c, p, a, pal: card_post(sc, c, p, a),
         "pair": card_pair, "rows": card_rows, "timeline": card_timeline, "image": card_image}


# --------------------------------------------------------------------------- sfx

SFX_LEN = {"whoosh": 0.9, "ding": 1.2, "thud": 0.8}


def synth_sfx(dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    f = ffmpeg()
    jobs = {
        "whoosh.wav": ["-f", "lavfi", "-i", "anoisesrc=d=0.9:c=pink:a=0.6", "-af",
                       "highpass=f=300,lowpass=f=4000,afade=t=in:d=0.45,afade=t=out:st=0.5:d=0.4,volume=0.8"],
        "ding.wav": ["-f", "lavfi", "-i", "sine=f=1318:d=1.2", "-f", "lavfi", "-i", "sine=f=1975:d=1.2", "-filter_complex",
                     "[0][1]amix=inputs=2,afade=t=out:st=0.05:d=1.1,volume=0.9"],
        "thud.wav": ["-f", "lavfi", "-i", "sine=f=70:d=0.8", "-f", "lavfi", "-i", "anoisesrc=d=0.12:c=brown:a=0.8", "-filter_complex",
                     "[0]afade=t=out:st=0.02:d=0.7[a];[1]lowpass=f=600[b];[a][b]amix=inputs=2,volume=1.6"],
    }
    for name, args in jobs.items():
        if not (dest / name).exists():
            run([f, "-v", "error", "-y", *args, "-ar", "48000", "-ac", "2", str(dest / name)])


# --------------------------------------------------------------------------- captions

def caption_layer(caps, spec, face: Face, pip_windows, punches, pal, fonts_css, proj):
    full = []
    t = 0.0
    for a, b in pip_windows:
        if a > t:
            full.append((t, a))
        t = b
    full.append((t, spec["_duration"] + 1))
    tops = {}
    for a, b in full:
        c = face.chin(a, b)
        for pa, pb in punches:  # punch-in moves the chin down
            if a <= pa < b:
                c = max(c, face.chin(pa, pb) * 1.1 - 40)
        tops[(a, b)] = min(int(c), 1560)
    hl = spec.get("highlight", {})
    words = sorted(((w, k) for k, ws in hl.items() for w in ws), key=lambda x: -len(x[0]))

    def mark(text):
        out, i = "", 0
        while i < len(text):
            for w, k in words:
                if text.startswith(w, i):
                    out += f'<span class="{ {"a": "ca", "b": "cb", "accent": "cy"}.get(k, "cy")}">{esc(w)}</span>'
                    i += len(w)
                    break
            else:
                out += esc(text[i])
                i += 1
        return out

    body, js = [], []
    end_all = spec.get("cta", {}).get("at", spec["_duration"]) - 0.05
    for i, c in enumerate(caps):
        st = max(0.1, c["start"] - 0.05)
        nxt = caps[i + 1]["start"] - 0.02 if i + 1 < len(caps) else end_all
        en = min(max(c["end"] + 0.25, st + 0.6), nxt)
        mid = (st + en) / 2
        seg = next(((a, b) for a, b in full if a <= mid < b), None)
        top = tops[seg] if seg else CAP_PIP_TOP
        body.append(f'<div id="cap{i}" class="cap" style="top:{top}px">{mark(c["text"])}</div>')
        js.append(f'tl.set("#cap{i}",{{opacity:1,visibility:"visible"}},{st:.2f}); tl.set("#cap{i}",{{opacity:0,visibility:"hidden"}},{en:.2f});')
    (proj / "compositions" / "captions.html").write_text(f"""<template>
<style>{fonts_css}:root{{--a:{pal['a']};--b:{pal['b']};--accent:{pal['accent']}}}
#root{{position:absolute;inset:0;}}
.cap{{position:absolute;left:0;width:1080px;text-align:center;font-family:'Display';font-weight:900;font-size:62px;line-height:1.2;color:#fff;
-webkit-text-stroke:12px #0a0f1a;paint-order:stroke fill;text-shadow:0 6px 16px rgba(0,0,0,.55);opacity:0;visibility:hidden}}
.ca{{color:var(--a)}}.cb{{color:var(--b)}}.cy{{color:var(--accent)}}
</style>
<div id="root" data-composition-id="captions" data-width="{W}" data-height="{H}">
{chr(10).join(body)}
</div>
<script>
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(js)}
window.__timelines["captions"] = tl;
</script>
</template>
""", encoding="utf-8")
    return tops


# --------------------------------------------------------------------------- court

def court_svg():
    M, B = 72, 1920
    hoop = B - 1.575 * M
    r3, cx3 = 6.75 * M, 0.9 * M
    dy = (r3 ** 2 - (540 - cx3) ** 2) ** 0.5
    y = lambda m: B - m * M  # noqa: E731
    return f"""<svg width="1080" height="1920" style="position:absolute;inset:0;opacity:.09" fill="none" stroke="#fff" stroke-width="4">
<line x1="0" y1="{y(14):.0f}" x2="1080" y2="{y(14):.0f}"/><circle cx="540" cy="{y(14):.0f}" r="{1.8 * M:.0f}"/>
<rect x="{540 - 2.45 * M:.0f}" y="{y(5.8):.0f}" width="{4.9 * M:.0f}" height="{5.8 * M + 4:.0f}"/><circle cx="540" cy="{y(5.8):.0f}" r="{1.8 * M:.0f}"/>
<line x1="{cx3:.0f}" y1="{B}" x2="{cx3:.0f}" y2="{hoop - dy:.0f}"/><line x1="{1080 - cx3:.0f}" y1="{B}" x2="{1080 - cx3:.0f}" y2="{hoop - dy:.0f}"/>
<path d="M {cx3:.0f} {hoop - dy:.0f} A {r3:.0f} {r3:.0f} 0 0 1 {1080 - cx3:.0f} {hoop - dy:.0f}"/>
<path d="M {540 - 1.25 * M:.0f} {hoop:.0f} A {1.25 * M:.0f} {1.25 * M:.0f} 0 0 1 {540 + 1.25 * M:.0f} {hoop:.0f}"/>
<line x1="{540 - 0.9 * M:.0f}" y1="{y(1.2):.0f}" x2="{540 + 0.9 * M:.0f}" y2="{y(1.2):.0f}"/><circle cx="540" cy="{hoop:.0f}" r="{0.225 * M:.0f}"/></svg>"""


# --------------------------------------------------------------------------- main build

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--project", help="Project dir (default: <spec dir>/包装)")
    a = ap.parse_args()
    spec_path = Path(a.spec).expanduser().resolve()
    root = spec_path.parent
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    rel = lambda p: (root / p).expanduser().resolve() if p else None  # noqa: E731
    proj = Path(a.project).expanduser().resolve() if a.project else root / "包装"
    if not (proj / "hyperframes.json").exists():
        proj.parent.mkdir(parents=True, exist_ok=True)
        run(["npx", "--yes", "hyperframes", "init", str(proj), "--skip-skills", "--resolution=portrait",
             "--non-interactive"], stdout=subprocess.DEVNULL)
    for d in ("compositions", "assets/fonts", "assets/img", "assets/sfx"):
        (proj / d).mkdir(parents=True, exist_ok=True)
    for old in (proj / "compositions").glob("*.html"):
        old.unlink()

    # footage: 1 s keyframes so seeking never freezes
    video = rel(spec["video"])
    talk = proj / "assets/talk.mp4"
    if not talk.exists() or talk.stat().st_mtime < video.stat().st_mtime:
        print("Preparing footage ...", flush=True)
        run([ffmpeg(), "-v", "error", "-y", "-i", str(video), "-c:v", "libx264", "-crf", "17", "-preset", "medium",
             "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(talk)])
    vdur = probe_duration(talk)
    tail = spec.get("cta", {}).get("hold", 3.0) if spec.get("cta") else 0
    dur = round(spec.get("duration") or (vdur + tail), 2)
    spec["_duration"] = dur

    copied = {}

    def assets(p):
        src = rel(p)
        if src in copied:
            return copied[src]
        if not src or not src.exists():
            die(f"Missing asset: {p}")
        dst = proj / "assets/img" / f"{len(copied):02d}_{src.name}"
        shutil.copy2(src, dst)
        copied[src] = f"assets/img/{dst.name}"
        return copied[src]

    pal = {"a": "#8BD400", "b": "#FF3B4E", "accent": "#FFC72C", "ground": "#070b14", **spec.get("palette", {})}
    css_vars = f"--a:{pal['a']};--b:{pal['b']};--accent:{pal['accent']}"
    fonts = find_fonts(spec.get("fonts"), proj / "assets/fonts")
    fcss = font_css(fonts)
    face = Face(rel(spec.get("face")))
    scenes: list[Scene] = []

    # hook
    if spec.get("hook"):
        h = spec["hook"]
        sc = Scene("hook", 0, h["until"], css_vars, fcss)
        sc.el('<div id="h-scrim" class="scrim" style="height:720px"></div>')
        if h.get("tag"):
            sc.el(f'<div id="h-tag" class="tag">{rich(h["tag"])}</div>')
        for i, line in enumerate(h["lines"]):
            sc.el(f'<div id="h-l{i}" class="ttl" style="top:{368 + i * 110}px;font-size:{h.get("size", 92)}px">{rich(line)}</div>')
        ids = ["#h-scrim", "#h-tag"] * bool(h.get("tag")) + [f"#h-l{i}" for i in range(len(h["lines"]))]
        ids = [i for i in dict.fromkeys(ids + ["#h-scrim"])]
        sc.js.append(f'tl.set({json.dumps(ids)},{{opacity:1}},0);')
        sc.js.append(f'OUT({json.dumps(ids)},{sc.t(h["until"]) - 0.35:.2f});')
        scenes.append(sc)

    # PiP windows and their cards
    pip_windows = [(w["start"], w["end"]) for w in spec.get("pip", [])]
    n = 0
    for w in spec.get("pip", []):
        for c in w["cards"]:
            n += 1
            cid = f"card{n:02d}"
            sc = Scene(cid, c["start"], c["end"], css_vars, fcss)
            p = f"c{n}"
            ids = header(sc, c, p)
            ids += CARDS[c["type"]](sc, c, p, assets, pal)
            sc.js.append(f'OUT({json.dumps(ids)},{sc.t(c["end"]) - 0.35:.2f});')
            scenes.append(sc)

    # finale line (full frame, top band)
    if spec.get("finale"):
        f = spec["finale"]
        st = f["at"][0] - 0.4
        end = spec.get("cta", {}).get("at", vdur)
        sc = Scene("finale", st, end, css_vars, fcss)
        sc.el('<div id="f-scrim" class="scrim" style="height:640px"></div>')
        sc.js.append(f'tl.fromTo("#f-scrim",{{opacity:0}},{{opacity:1,duration:0.4}},0);')
        for i, line in enumerate(f["lines"]):
            sc.el(f'<div id="f-l{i}" class="ttl" style="top:{318 + i * 110}px;font-size:{f.get("size", 84)}px">{rich(line)}</div>')
            at = f["at"][min(i, len(f["at"]) - 1)]
            sc.js.append(f'IN("#f-l{i}",{sc.t(at):.2f}{",{y:0,scale:1.2}" if i == len(f["lines"]) - 1 and i else ""});')
        scenes.append(sc)

    # CTA end card
    if spec.get("cta"):
        c = spec["cta"]
        sc = Scene("cta", c["at"], dur, css_vars, fcss)
        sc.el('<div id="e-bg" style="position:absolute;inset:0;background:radial-gradient(ellipse at 50% 35%,#16264a,#070b14 70%)"></div>')
        imgs = c.get("images", [])
        if imgs:
            cols = c.get("image_colors", ["a", "b"])
            tags = "".join(f'<img src="{assets(x)}" style="width:435px;height:420px;object-fit:cover;object-position:50% 18%;border-radius:20px;border:5px solid {pal.get(cols[i % len(cols)], cols[i % len(cols)])}">'
                           for i, x in enumerate(imgs[:2]))
            sc.el(f'<div id="e-imgs" style="position:absolute;left:0;top:330px;width:1080px;display:flex;justify-content:center;gap:30px">{tags}</div>')
            sc.js.append('IN("#e-imgs",0.2,{y:60});')
        for i, line in enumerate(c["lines"]):
            sc.el(f'<div id="e-l{i}" class="ttl" style="left:0;top:{800 + i * 95}px;width:1080px;text-align:center;font-size:72px">{rich(line)}</div>')
            sc.js.append(f'IN("#e-l{i}",{0.45 + 0.15 * i:.2f});')
        if c.get("button"):
            sc.el(f'<div style="position:absolute;left:0;top:{800 + len(c["lines"]) * 95 + 50}px;width:1080px;text-align:center"><span id="e-btn" class="tag" style="position:relative;left:0;top:0;font-size:40px;padding:10px 40px">{rich(c["button"])}</span></div>')
            sc.js.append('tl.fromTo("#e-btn",{opacity:0,scale:0.8},{opacity:1,scale:1,duration:0.35,ease:"back.out(2)"},0.9);')
        if c.get("credits"):
            sc.el(f'<div id="e-cred" data-layout-ignore style="position:absolute;left:60px;top:1700px;width:960px;font-size:20px;line-height:1.5;color:rgba(255,255,255,.45);font-weight:500">{"<br>".join(esc(x) for x in c["credits"])}</div>')
            sc.js.append('tl.fromTo("#e-cred",{opacity:0},{opacity:1,duration:0.4},0.5);')
        sc.js.insert(0, 'tl.fromTo("#e-bg",{opacity:0},{opacity:1,duration:0.35},0);')
        scenes.append(sc)

    for sc in scenes:
        sc.write(proj)

    # captions
    punches = [(p["at"], p.get("until", p["at"] + 1.5)) for p in spec.get("punch", [])]
    caps = json.loads(rel(spec["captions"]).read_text(encoding="utf-8")) if spec.get("captions") else []
    tops = caption_layer(caps, spec, face, pip_windows, punches, pal, fcss, proj) if caps else {}

    # camera: PiP windows follow the face; punch-ins zoom about the face
    cam = ['tl.set("#ring",{opacity:0,scale:0.9},0);', f'tl.set("#cam",{{{FULL}}},0);']
    for a0, b0 in pip_windows:
        cam.append(f'tl.to("#cam",{{{face.crop(a0 + 0.6)},duration:0.6,ease:"power3.inOut"}},{a0});')
        cam.append(f'tl.to("#ring",{{opacity:1,scale:1,duration:0.3,ease:"power2.out"}},{a0 + 0.45:.2f});')
        t = a0 + 0.6
        while t + 0.4 <= b0 + 1e-6:
            cam.append(f'tl.to("#cam",{{{face.crop(t + 0.4)},duration:0.4,ease:"sine.inOut"}},{t:.2f});')
            t += 0.4
        cam.append(f'tl.to("#ring",{{opacity:0,scale:0.9,duration:0.15}},{b0});')
        cam.append(f'tl.fromTo("#cam",{{{face.crop(t)}}},{{{FULL},duration:0.6,ease:"power3.inOut"}},{b0});')
    for pa, pb in punches:
        x, y, w, h = face.at(pa)
        k = 1.1
        fx, fy = x + w / 2, y + h / 2
        cam.append(f'tl.to("#cam",{{scale:{k},x:{fx * (1 - k):.1f},y:{fy * (1 - k):.1f},duration:0.25,ease:"power3.out"}},{pa});')
        if not any(abs(pb - a0) < 0.05 for a0, _ in pip_windows):
            cam.append(f'tl.to("#cam",{{scale:1,x:0,y:0,duration:0.25,ease:"power3.out"}},{pb});')

    # audio: music bed + synthesized sfx on transitions and reveals
    audio = []
    if spec.get("bgm"):
        b = spec["bgm"]
        src = rel(b["file"])
        ext = src.suffix
        shutil.copy2(src, proj / f"assets/bgm{ext}")
        audio.append(f'<audio id="bgm" class="clip" src="assets/bgm{ext}" data-start="0" data-media-start="{b.get("offset", 0)}" data-duration="{dur}" '
                     f'data-volume="{b.get("volume", 0.13)}" data-fade-in="0.5" data-fade-out="1.8" data-track-index="5"></audio>')
    if spec.get("sfx", True):
        synth_sfx(proj / "assets/sfx")
        hits = []
        for a0, b0 in pip_windows:
            hits += [("whoosh", a0 - 0.15, 0.3), ("whoosh", b0 - 0.15, 0.25)]
        for w in spec.get("pip", []):
            for c in w["cards"]:
                if c["type"] == "pair" and c.get("reveal") is not None:
                    hits.append(("ding", c["reveal"], 0.25))
                if c["type"] == "pair" and c.get("stamp"):
                    hits.append(("thud", c["stamp"]["at"] + 0.25, 0.45))
        if spec.get("cta"):
            hits.append(("ding", spec["cta"]["at"] + 0.4, 0.2))
        for i, (nm, st, vol) in enumerate(sorted(hits, key=lambda x: x[1])):
            audio.append(f'<audio id="sfx{i}" class="clip" src="assets/sfx/{nm}.wav" data-start="{max(0, st):.2f}" data-duration="{SFX_LEN[nm]}" data-volume="{vol}" data-track-index="4"></audio>')

    hosts = []
    for sc in scenes:
        lane = 2 if sc.cid in ("cta",) else 1
        z = 20 if sc.cid == "cta" else 5
        hosts.append(f'<div id="{sc.cid}" data-composition-id="{sc.cid}" data-composition-src="compositions/{sc.cid}.html" data-start="{sc.start}" '
                     f'data-duration="{sc.end - sc.start:.2f}" data-track-index="{lane}" data-track-kind="graphics" data-width="{W}" data-height="{H}" style="z-index:{z}"></div>')
    if caps:
        hosts.append(f'<div id="captions" data-composition-id="captions" data-composition-src="compositions/captions.html" data-start="0" data-duration="{dur}" '
                     f'data-track-index="3" data-track-kind="captions" data-width="{W}" data-height="{H}" style="z-index:10"></div>')
    bg = court_svg() if spec.get("background", "court") == "court" else ""
    index = f"""<!doctype html>
<html lang="zh" data-resolution="portrait">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={W}, height={H}" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:{pal['ground']}}}
#root{{width:100%;height:100%;position:relative}}
#bg{{position:absolute;inset:0;z-index:0;background:radial-gradient(circle at 12% 30%,{pal['a']}33,transparent 45%),radial-gradient(circle at 92% 70%,{pal['b']}38,transparent 45%),linear-gradient(#0b1224,{pal['ground']})}}
#cam{{position:absolute;inset:0;z-index:1;transform-origin:0 0}}
#talk{{position:absolute;inset:0;width:{W}px;height:{H}px;object-fit:cover}}
#ring{{position:absolute;left:{BOX[0] - 6}px;top:{BOX[1] - 6}px;width:{BOX[2] + 12}px;height:{BOX[3] + 12}px;border-radius:{BOX[2] // 2 + 6}px;border:6px solid {pal['accent']};z-index:2;opacity:0;box-shadow:0 16px 40px rgba(0,0,0,.5)}}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{W}" data-height="{H}">
<div id="bg">{bg}</div>
<div id="cam"><video id="talk" class="clip" src="assets/talk.mp4" data-start="0" data-duration="{vdur:.2f}" data-track-index="0" data-has-audio="true" playsinline></video></div>
<div id="ring"></div>
{chr(10).join(audio)}
{chr(10).join(hosts)}
</div>
<script>
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(cam)}
window.__timelines["main"] = tl;
</script>
</body>
</html>
"""
    (proj / "index.html").write_text(index, encoding="utf-8")
    print(f"Built {proj}\n  {len(scenes)} graphic scenes, {len(caps)} captions, {len(pip_windows)} PiP windows, "
          f"{len(punches)} punch-ins, duration {dur}s")
    if tops:
        print("  caption tops by full-frame section:", {f"{a:.1f}-{b:.1f}": v for (a, b), v in tops.items()})


if __name__ == "__main__":
    main()

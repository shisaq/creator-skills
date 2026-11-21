#!/usr/bin/env python3
"""3:4 cover (1080×1440) from the packaging spec's "cover" block.

    python3 cover.py spec.json [--out cover.png] [--size 1080x1440]

"cover": {"frame": 88.6, "tag": "…", "lines": ["逼走{a:黄仁勋}", "＝让{b:乔丹}离开{b:公牛}"],
          "sub": "这个比喻里，藏着{u:两个彩蛋}", "people": ["img/a.jpg", "img/b.jpg"],
          "badge": "同年同月同日生", "value": "1963.02.17"}

The speaker frame is taken from the refined cut at `frame` seconds; pick one where they smile with
eyes open (look at a contact sheet first). Rendered with headless Chrome.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import find_fonts, rich  # noqa: E402


def chrome():
    env = os.environ.get("HYPERFRAMES_BROWSER_PATH")
    cands = [env] if env else []
    cands += sorted(glob.glob(str(Path.home() / ".cache/hyperframes/chrome/chrome-headless-shell/*/*/chrome-headless-shell")))[::-1]
    cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", shutil.which("google-chrome") or "",
              shutil.which("chromium") or ""]
    for c in cands:
        if c and Path(c).exists():
            return c
    raise SystemExit("No Chrome found (install Google Chrome, or run a HyperFrames render once).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out")
    ap.add_argument("--size", default="1080x1440")
    a = ap.parse_args()
    sp = Path(a.spec).expanduser().resolve()
    root = sp.parent
    spec = json.loads(sp.read_text(encoding="utf-8"))
    c = spec["cover"]
    pal = {"a": "#8BD400", "b": "#FF3B4E", "accent": "#FFC72C", "ground": "#070b14", **spec.get("palette", {})}
    W, H = (int(x) for x in a.size.split("x"))
    work = root / "封面_work"
    work.mkdir(exist_ok=True)
    fonts = find_fonts(spec.get("fonts"), work / "fonts")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(c.get("frame", 1.0)), "-i", str((root / spec["video"]).resolve()),
                    "-frames:v", "1", str(work / "host.png")], check=True)
    people = []
    for i, p in enumerate(c.get("people", [])[:2]):
        dst = work / f"p{i}{Path(p).suffix}"
        shutil.copy2((root / p).resolve(), dst)
        people.append(dst.name)
    face = None
    if spec.get("face") and (root / spec["face"]).exists():
        s = [x for x in json.loads((root / spec["face"]).read_text())["samples"] if x[1] is not None]
        if s:
            face = min(s, key=lambda x: abs(x[0] - c.get("frame", 1.0)))
    fx, fy = ((face[1] + face[3] / 2), (face[2] + face[4] / 2)) if face else (540, 950)
    k = 0.8
    left, top = int(W * 0.667 - fx * k), int(H * 0.69 - fy * k)
    w = {"heavy": 900, "bold": 700, "medium": 500}
    ff = "".join(f"@font-face{{font-family:'Display';src:url('fonts/{fn}');font-weight:{w[r]}}}" for r, fn in fonts.items())
    lines = c.get("lines", [])
    size = c.get("size", 112)
    titles = "".join(f'<div class="t" style="top:{178 + i * int(size * 1.23)}px;font-size:{size}px">{rich(x)}</div>' for i, x in enumerate(lines))
    sub_top = 178 + len(lines) * int(size * 1.23) + 10
    pair = ""
    if people:
        cols = [pal["a"], pal["b"]]
        imgs = "".join(f'<img class="ph" src="{p}" style="left:{i * 190}px;top:20px;border:7px solid {cols[i]}">' for i, p in enumerate(people))
        badge = (f'<div class="badge"><b>{rich(c.get("badge", ""))}</b><span>{rich(c.get("value", ""))}</span></div>'
                 if c.get("badge") else "")
        pair = f'<div class="pair" style="top:{sub_top + 150}px">{imgs}{badge}</div>'
    doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><style>{ff}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:{pal['ground']};font-family:'Display',sans-serif;color:#fff}}
.host{{position:absolute;left:{left}px;top:{top}px;width:{int(1080 * k)}px;height:{int(1920 * k)}px;object-fit:cover;
-webkit-mask-image:linear-gradient(90deg,transparent 0,#000 30%),linear-gradient(180deg,transparent 0,#000 22%);-webkit-mask-composite:source-in;mask-composite:intersect}}
.fade{{position:absolute;inset:0;background:linear-gradient(90deg,{pal['ground']} 30%,rgba(7,11,20,.7) 44%,rgba(7,11,20,0) 62%),linear-gradient(180deg,{pal['ground']} 0%,rgba(7,11,20,.9) 22%,rgba(7,11,20,0) 42%),linear-gradient(0deg,rgba(7,11,20,.85) 0%,rgba(7,11,20,0) 22%)}}
.glow{{position:absolute;inset:0;background:radial-gradient(circle at 10% 18%,{pal['a']}47,transparent 40%),radial-gradient(circle at 95% 8%,{pal['b']}40,transparent 38%)}}
.tag{{position:absolute;left:70px;top:86px;padding:8px 26px;border:3px solid {pal['accent']};border-radius:40px;color:{pal['accent']};font-weight:700;font-size:38px}}
.t{{position:absolute;left:66px;font-weight:900;line-height:1;letter-spacing:2px;white-space:nowrap;text-shadow:0 8px 30px rgba(0,0,0,.6)}}
.ca{{color:{pal['a']}}}.cb{{color:{pal['b']}}}.cy{{color:{pal['accent']}}}.cm{{color:#9FB4D9}}
.ul{{border-bottom:7px solid {pal['accent']};padding-bottom:4px}}
.sub{{position:absolute;left:70px;top:{sub_top}px;font-size:46px;font-weight:700}}
.pair{{position:absolute;left:70px;width:430px}}
.ph{{position:absolute;width:230px;height:230px;border-radius:50%;object-fit:cover;object-position:50% 18%;box-shadow:0 14px 40px rgba(0,0,0,.6)}}
.badge{{position:absolute;left:0;top:300px;width:430px;text-align:center}}
.badge b{{display:inline-block;padding:10px 0;width:400px;border-radius:16px;background:{pal['accent']};color:#0a0f1a;font-size:40px;font-weight:900}}
.badge span{{display:block;margin-top:14px;font-size:62px;font-weight:900;letter-spacing:3px;color:{pal['accent']};text-shadow:0 6px 20px rgba(0,0,0,.6)}}
</style></head><body>
<img class="host" src="host.png"><div class="fade"></div><div class="glow"></div>
{f'<div class="tag">{rich(c["tag"])}</div>' if c.get("tag") else ""}{titles}
{f'<div class="sub">{rich(c["sub"])}</div>' if c.get("sub") else ""}{pair}
</body></html>"""
    (work / "cover.html").write_text(doc, encoding="utf-8")
    out = Path(a.out).expanduser().resolve() if a.out else root / "封面_3x4.png"
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                    "--force-device-scale-factor=1", f"--window-size={W},{H}", "--virtual-time-budget=5000",
                    f"--screenshot={out}", (work / "cover.html").as_uri()], check=True, capture_output=True)
    print(out)


if __name__ == "__main__":
    main()

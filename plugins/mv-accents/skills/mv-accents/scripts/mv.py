#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy>=1.22", "pillow>=9.2", "imageio-ffmpeg>=0.5"]
# ///
"""mv-accents: music-driven accents for performance videos (piano, singing, any instrument).

  doctor                              check ffmpeg / fonts
  look   <video> [--every 8] [--grid 12.5 ...]   contact sheet / coordinate grid / colour palette
  music  <video> [--meter 3]          tempo, beat reliability, where it's quiet / loud
  init   <video>                      write a starter plan next to the video
  check  <plan>                       validate + test-draw every effect (incl. your own)
  still  <plan> [--at 12.5 ...]       a few finished-looking frames (fast)
  render <plan> [--mode burn|overlay|both]

Run with `uv run mv.py ...`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core import custom, look, media  # noqa: E402
from core.base import Ctx, composite_still  # noqa: E402

DEFAULT_STYLE = {"accent": "#FFC43D", "dark": "#1E1A16", "font": "", "title_font": "", "sfx": False}


def plan_path_for(video: Path) -> Path:
    return video.parent / f"{video.stem}_特效方案.json"


def work_for(video: Path) -> Path:
    return video.parent / f"{video.stem}_特效素材"


def get_beats(video: Path, meter: int = 4, force=False):
    import beats

    f = work_for(video) / "beats.json"
    mt = video.stat().st_mtime
    if f.exists() and not force:
        b = json.loads(f.read_text(encoding="utf-8"))
        if b.get("meter") == meter and b.get("_mtime") == mt:
            return b
    meta = media.probe(video)
    if not meta["has_audio"]:
        return None
    print("分析音乐…", flush=True)
    b = beats.analyze(media.audio_mono(video, beats.SR), meter=meter)
    b["_mtime"] = mt
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    return b


def load(arg: str):
    p = Path(arg).expanduser().resolve()
    if p.suffix.lower() != ".json":
        pp = plan_path_for(p)
        if not pp.exists():
            raise SystemExit(f"还没有方案：{pp.name}。先运行 `mv.py init \"{p}\"`。")
        p = pp
    try:
        plan = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{p.name} 不是合法 JSON：第 {e.lineno} 行第 {e.colno} 列 {e.msg}（常见：多余逗号、中文引号、注释）")
    v = Path(str(plan.get("video", ""))).expanduser()
    if not v.is_absolute():
        v = (p.parent / v).resolve()
    if not v.exists():
        raise SystemExit(f"方案里的 video 找不到：{plan.get('video')}")
    plan["style"] = {**DEFAULT_STYLE, **(plan.get("style") or {})}
    return plan, p, v


def validate(plan, meta):
    import effects

    errs, warns = [], []
    D = meta["duration"]
    effs = plan.get("effects") or []
    if not effs:
        errs.append("effects 是空的。")
    if not meta["has_audio"]:
        errs.append("视频没有声音，没法跟音乐。")
    for i, e in enumerate(effs, 1):
        typ = e.get("type")
        if typ not in effects.BUILTIN and typ != "custom":
            errs.append(f"effects 第 {i} 项 type={typ!r} 不认识；内置有 {', '.join(effects.BUILTIN)}，自己写的用 custom。")
        for k in ("from", "to", "start"):
            if e.get(k) is not None and not (isinstance(e[k], (int, float)) and 0 <= e[k] <= D):
                errs.append(f"effects 第 {i} 项（{typ}）的 {k}={e[k]} 要是 0–{D:.1f} 之间的秒数（或 null）。")
        if e.get("from") is not None and e.get("to") is not None and e["to"] <= e["from"]:
            errs.append(f"effects 第 {i} 项（{typ}）的 to 不晚于 from。")
        if e.get("sync", "auto") not in ("auto", "beats", "onsets"):
            errs.append(f"effects 第 {i} 项的 sync 只能是 auto / beats / onsets。")
        if typ == "custom" and not (e.get("file") and e.get("class")):
            errs.append(f"effects 第 {i} 项是 custom，要写 file（.py）和 class。")
        for a in e.get("anchors") or []:
            if not (isinstance(a, list) and len(a) == 2 and 0 <= a[0] <= meta["width"] and 0 <= a[1] <= meta["height"]):
                errs.append(f"effects 第 {i} 项的 anchors 里 {a} 不在画面 {meta['width']}x{meta['height']} 内。")
        if typ in ("pulse", "sparkles") and float(e.get("strength", 1)) > 1.5:
            warns.append(f"effects 第 {i} 项 strength>1.5，通常会抢戏。")
    n_full = sum(1 for e in effs if e.get("type") in ("pulse", "sparkles") and e.get("from") is None and e.get("to") is None)
    if n_full >= 2:
        warns.append("有两个以上律动效果从头开到尾。通常让它们跟着段落强弱分开出现，更有层次（见 SKILL.md）。")
    mode = (plan.get("output") or {}).get("mode", "burn")
    if mode not in ("burn", "overlay", "both"):
        errs.append("output.mode 只能是 burn / overlay / both。")
    if meta.get("hdr") and mode != "overlay":
        warns.append("HDR 视频：直接合成后颜色可能发灰，建议先导出 SDR 版本，或用 overlay 模式。")
    return errs, warns


def build(plan, plan_path, video):
    import effects
    from music import Music

    meta = media.probe(video)
    ctx = Ctx(meta, plan["style"])
    meter = int(plan.get("meter", 4))
    ctx.music = Music(get_beats(video, meter), meta["duration"])
    els = []
    customs = []
    for e in plan.get("effects") or []:
        if e.get("type") == "custom":
            customs.append(e)
        else:
            els.append(effects.BUILTIN[e["type"]](ctx, e))
    els += custom.build(ctx, customs, plan_path.parent)
    els = [e for e in els if e.end > e.start]
    els.sort(key=lambda e: (e.layer, e.start))
    return meta, ctx, els


def picks_for(els):
    out, seen = [], set()
    for e in els:
        t = e.preview_time()
        if round(t, 1) not in seen:
            seen.add(round(t, 1))
            out.append((t, e.label))
    return out


# ----------------------------------------------------------------------------- commands
def cmd_doctor(a):
    from core import fonts

    print(f"ffmpeg：{media.ffmpeg()}")
    enc = media.encoders()
    print("编码器：" + "，".join(f"{n} {'✓' if n in enc else '✗'}" for n in ("qtrle", "prores_ks", "libx264")))
    f = fonts.resolve()
    print(f"中文字体：{f['ui'][0].name}（标题用 {f['title'][0].name}）")
    print("环境没问题。下一步：`look <视频>` 和 `music <视频>`。")


def cmd_look(a):
    video = Path(a.video).expanduser().resolve()
    meta = media.probe(video)
    work = work_for(video)
    work.mkdir(parents=True, exist_ok=True)
    D = meta["duration"]
    print(f"视频 {meta['width']}x{meta['height']}（{'竖屏' if meta['height'] > meta['width'] else '横屏'}），"
          f"{D:.1f} 秒，{meta['fps']:.0f} fps{'，HDR' if meta['hdr'] else ''}")
    if a.grid:
        for t in a.grid:
            print(f"坐标网格 {media.fmt_time(t)}：{look.grid_frame(video, meta, t, work / f'grid_{t:.1f}.jpg')}")
    else:
        every = a.every or max(3.0, round(D / 24))
        times = [min(D - 0.1, i * every + every / 2) for i in range(int(D // every) + 1)][:36]
        print(f"缩略图（每 {every:.0f} 秒一张）：{look.contact_sheet(video, meta, times, work / f'contact_{int(every)}s.jpg')}")
        pal = look.palette(video, meta, times[:: max(1, len(times) // 6)][:6])
        print("画面主色：\n" + look.describe_palette(pal))
    print("下一步：看图弄清人、手、乐器在哪（效果要避开），再 `music` 看音乐结构。")


def cmd_music(a):
    from music import Music

    video = Path(a.video).expanduser().resolve()
    b = get_beats(video, a.meter, force=True)
    if not b:
        raise SystemExit("视频没有声音。")
    m = Music(b, media.probe(video)["duration"])
    T = media.fmt_time
    print(f"速度约 {b['bpm']} BPM（{b['meter']} 拍），拍点与音符吻合 {b['agreement']:.0%} → "
          f"{'节拍稳定，sync=auto 会跟拍子' if b['steady'] else '自由速度/节拍不清，sync=auto 会跟音符起音'}")
    print("有音乐：" + ("、".join(f"{T(x)}–{T(y)}" for x, y in b["music"]) or "没检测到"))
    print("强弱结构（按响度粗分，用来决定哪里收、哪里放）：")
    for s, e, lab in m.sections():
        print(f"  {T(s)}–{T(e)}  {lab}")
    print(f"拍点 {len(b['beats'])} 个，重拍 {len(b['downbeats'])} 个，明显的音符起音 {sum(1 for o in b['onsets'] if o[1] >= 0.6)} 个。")
    print("下一步：按 SKILL.md 的原则设计效果，`init` 后写方案。")


def cmd_init(a):
    video = Path(a.video).expanduser().resolve()
    pp = plan_path_for(video)
    if pp.exists() and not a.force:
        print(f"方案已存在：{pp}（重来加 --force）")
        return
    meta = media.probe(video)
    plan = {
        "video": video.name,
        "meter": 4,
        "style": dict(DEFAULT_STYLE),
        "effects": [
            {"type": "song_card", "title": video.stem, "sub": "", "start": 0.8, "dur": 6},
            {"type": "pulse", "from": None, "to": None, "sync": "auto", "strength": 0.8},
        ],
        "output": {"mode": "burn"},
    }
    pp.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成：{pp}\n视频 {meta['width']}x{meta['height']}，{meta['duration']:.1f} 秒。这只是起点，按设计改 effects，然后 check。")


def _prepare(a):
    plan, pp, video = load(a.plan)
    meta = media.probe(video)
    errs, warns = validate(plan, meta)
    for w in warns:
        print("提醒：" + w)
    for e in errs:
        print("✗ " + e)
    if errs:
        sys.exit(2)
    meta, ctx, els = build(plan, pp, video)
    bad = custom.smoke_test(els)
    for b in bad:
        print("✗ " + b)
    if bad:
        sys.exit(2)
    return plan, pp, video, meta, ctx, els


def cmd_check(a):
    plan, pp, video, meta, ctx, els = _prepare(a)
    print(f"✓ 没问题：{len(els)} 个效果")
    for e in els:
        print(f"  {media.fmt_time(e.start)}–{media.fmt_time(e.end)}  {e.label}")
    print("下一步：`still` 出几帧看效果。")


def cmd_still(a):
    plan, pp, video, meta, ctx, els = _prepare(a)
    times = a.at or [t for t, _ in picks_for(els)][:4]
    work = work_for(video)
    for t in times:
        im = composite_still(els, media.frame(video, t, ctx.W, ctx.H), t)
        im.thumbnail((1600, 1600))
        out = work / f"still_{t:.2f}.jpg"
        im.save(out, quality=90)
        print(f"{media.fmt_time(t)} → {out}")
    print("下一步：看图检查（SKILL.md「检查清单」）。律动要看动态的话直接 render 看成片。")


def cmd_render(a):
    from core import compose

    plan, pp, video, meta, ctx, els = _prepare(a)
    mode = a.mode or (plan.get("output") or {}).get("mode", "burn")
    compose.produce(video, meta, ctx, els, mode, work_for(video), picks_for(els), plan["style"].get("sfx", False), "特效版")
    print("下一步：看检查图，再请用户看成片（律动是动态的，静帧判断不了节奏感）。改了方案再 render 只重画改动的效果。")


def main():
    ap = argparse.ArgumentParser(prog="mv.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("look")
    p.add_argument("video")
    p.add_argument("--every", type=float)
    p.add_argument("--grid", type=float, action="append")
    p.set_defaults(fn=cmd_look)
    p = sub.add_parser("music")
    p.add_argument("video")
    p.add_argument("--meter", type=int, default=4, help="每小节几拍，华尔兹填 3")
    p.set_defaults(fn=cmd_music)
    p = sub.add_parser("init")
    p.add_argument("video")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)
    for name, fn in (("check", cmd_check), ("still", cmd_still), ("render", cmd_render)):
        p = sub.add_parser(name)
        p.add_argument("plan", help="方案 json，或视频（自动找旁边的方案）")
        if name == "still":
            p.add_argument("--at", type=float, action="append")
        if name == "render":
            p.add_argument("--mode", choices=["burn", "overlay", "both"])
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

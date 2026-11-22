#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy>=1.22", "pillow>=9.2", "imageio-ffmpeg>=0.5"]
# ///
"""chapter-bar: add a chapter progress bar to a tutorial / talking video.

  doctor                              check ffmpeg / fonts
  look   <video> [--every 20] [--grid 12.5 ...]   contact sheet / coordinate grid / colour palette
  init   <video>                      write a starter plan next to the video
  check  <plan>                       validate + test-draw every element
  still  <plan> [--at 12.5 ...]       a few finished-looking frames (fast)
  render <plan> [--mode burn|overlay|both]

Run with `uv run chapters.py ...`.
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

DEFAULT_STYLE = {"accent": "#FFC43D", "dark": "#1E1A16", "font": "", "title_font": "", "sfx": True}


def plan_path_for(video: Path) -> Path:
    return video.parent / f"{video.stem}_章节方案.json"


def work_for(video: Path) -> Path:
    return video.parent / f"{video.stem}_章节素材"


def load(arg: str):
    p = Path(arg).expanduser().resolve()
    if p.suffix.lower() != ".json":
        pp = plan_path_for(p)
        if not pp.exists():
            raise SystemExit(f"还没有方案：{pp.name}。先运行 `chapters.py init \"{p}\"`。")
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
    errs, warns = [], []
    D = meta["duration"]
    T = media.fmt_time
    ch = plan.get("chapters") or []
    if not ch:
        errs.append("chapters 是空的。至少写 3 章：[{\"start\": 0, \"title\": \"开场\"}, ...]")
    last = -1.0
    for i, c in enumerate(ch, 1):
        s = c.get("start")
        if not isinstance(s, (int, float)) or isinstance(s, bool):
            errs.append(f"第 {i} 章缺少数字 start（秒）。")
            continue
        if not str(c.get("title", "")).strip():
            errs.append(f"第 {i} 章（{T(s)}）没有 title。")
        if s < 0 or s >= D:
            errs.append(f"第 {i} 章「{c.get('title')}」start={s} 超出视频 0–{D:.1f} 秒。")
        if s <= last:
            errs.append(f"第 {i} 章「{c.get('title')}」start={s} 不晚于上一章；按时间顺序写，不能重复。")
        last = s
    good = [c for c in ch if isinstance(c.get("start"), (int, float))]
    if good and good[0]["start"] > 0.5:
        warns.append(f"第一章从 {T(good[0]['start'])} 开始，之前没有章节条，YouTube 章节也要求从 0:00 开始。通常把第一章 start 改成 0。")
    starts = [c["start"] for c in good] + [D]
    for i, c in enumerate(good):
        L = starts[i + 1] - starts[i]
        if L < 10:
            warns.append(f"「{c.get('title')}」只有 {L:.0f} 秒：章节条上会很窄，YouTube 也要求每章 ≥10 秒。考虑并入相邻章节。")
        if len(str(c.get("title", ""))) > 8:
            warns.append(f"章节名「{c.get('title')}」偏长（>8 字），条上可能放不下，会被收成胶囊只在当前章显示。")
    if len(good) > 10:
        warns.append(f"{len(good)} 章太多，条会很碎。讲解视频 4–8 章最合适。")
    bar = plan.get("bar") or {}
    if bar.get("position", "top") not in ("top", "bottom"):
        errs.append("bar.position 只能是 top 或 bottom。")
    mode = (plan.get("output") or {}).get("mode", "burn")
    if mode not in ("burn", "overlay", "both"):
        errs.append("output.mode 只能是 burn / overlay / both。")
    if meta.get("hdr") and mode != "overlay":
        warns.append("HDR 视频（iPhone 默认录制常见）：直接合成的成片颜色可能发灰，建议先导出 SDR 版本再做，或用 overlay 模式。")
    return errs, warns


def build(plan, plan_path, video):
    import bars

    meta = media.probe(video)
    ctx = Ctx(meta, plan["style"])
    els = bars.build(ctx, plan)
    if els and els[0].kind == "chapters":
        ctx.safe_top = els[0].y + els[0].h if (plan.get("bar") or {}).get("position", "top") == "top" else 0
    specs = [{**s, "items": s.get("items", plan.get("chapters") or [])} for s in plan.get("custom") or []]
    els += custom.build(ctx, specs, plan_path.parent)
    els.sort(key=lambda e: (e.layer, e.start))
    return meta, ctx, els


def picks_for(els):
    out = []
    for e in els:
        if hasattr(e, "preview_times"):
            out += e.preview_times()
        else:
            out.append((e.preview_time(), e.label))
    seen, res = set(), []
    for t, l in sorted(out):
        if round(t, 1) not in seen:
            seen.add(round(t, 1))
            res.append((t, l))
    return res


def youtube_txt(plan):
    ch = sorted(plan.get("chapters") or [], key=lambda c: c["start"])
    if len(ch) < 3:
        return None
    return "\n".join(f"{media.fmt_time(0 if i == 0 else c['start'])} {c['title']}" for i, c in enumerate(ch)) + "\n"


# ----------------------------------------------------------------------------- commands
def cmd_doctor(a):
    from core import fonts

    print(f"ffmpeg：{media.ffmpeg()}")
    enc = media.encoders()
    print("编码器：" + "，".join(f"{n} {'✓' if n in enc else '✗'}" for n in ("qtrle", "prores_ks", "libx264")))
    f = fonts.resolve()
    print(f"中文字体：{f['ui'][0].name}（标题用 {f['title'][0].name}）")
    print("环境没问题。下一步：`look <视频>` 了解视频内容。")


def cmd_look(a):
    video = Path(a.video).expanduser().resolve()
    meta = media.probe(video)
    work = work_for(video)
    work.mkdir(parents=True, exist_ok=True)
    D = meta["duration"]
    print(f"视频 {meta['width']}x{meta['height']}，{D:.1f} 秒（{media.fmt_time(D)}），{meta['fps']:.0f} fps"
          f"{'，HDR' if meta['hdr'] else ''}{'，有声音' if meta['has_audio'] else '，无声音'}")
    if a.grid:
        for t in a.grid:
            out = look.grid_frame(video, meta, t, work / f"grid_{t:.1f}.jpg")
            print(f"坐标网格 {media.fmt_time(t)}：{out}")
    else:
        every = a.every or max(5.0, round(D / 32))
        times = [min(D - 0.1, i * every + every / 2) for i in range(int(D // every) + 1)][:48]
        out = look.contact_sheet(video, meta, times, work / f"contact_{int(every)}s.jpg")
        print(f"缩略图（每 {every:.0f} 秒一张，共 {len(times)} 张）：{out}")
        pal = look.palette(video, meta, times[:: max(1, len(times) // 6)][:6])
        print("画面主色：\n" + look.describe_palette(pal))
    clip = video.parent / f"{video.stem}_chapters.json"
    if clip.exists():
        print(f"发现 meeting-clipper 的分段结果：{clip.name}。可以直接用它：`chapters.py from-clipper \"{clip}\" \"{video}\"`")
    srts = sorted(video.parent.glob(f"{video.stem}*.srt"))
    reading = sorted(video.parent.glob(f"{video.stem}*_阅读版.md"))
    if reading or srts:
        print("已有文字稿（分章节最好的依据）：" + "，".join(s.name for s in reading + srts))
        print("下一步：读文字稿（有阅读版先读阅读版），按 SKILL.md 的原则划分章节，`init` 后写进方案。")
    elif meta["has_audio"]:
        print("同目录没有字幕。下一步：转写一份再分章节——\n"
              f"  uv run \"{HERE / 'transcribe.py'}\" \"{video}\" --reading-copy\n"
              "（本地运行；第一次会下载约 240MB 语音模型，之后不再下载）")
    else:
        print("视频没有声音，只能靠缩略图和用户描述来分章节。")


def cmd_init(a):
    video = Path(a.video).expanduser().resolve()
    pp = plan_path_for(video)
    if pp.exists() and not a.force:
        print(f"方案已存在：{pp}（重来加 --force）")
        return
    meta = media.probe(video)
    plan = {
        "video": video.name,
        "style": dict(DEFAULT_STYLE),
        "bar": {"style": "tabs", "position": "top", "announce": False},
        "chapters": [{"start": 0, "title": "开场"}],
        "output": {"mode": "burn"},
    }
    pp.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成：{pp}\n视频 {meta['width']}x{meta['height']}，{meta['duration']:.1f} 秒。下一步：填 chapters，然后 check。")


def _secs(v):
    if isinstance(v, (int, float)):
        return float(v)
    parts = [float(x) for x in str(v).strip().split(":")]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def cmd_from_clipper(a):
    """Turn a meeting-clipper <video>_chapters.json (archive mode works best) into a chapter-bar plan."""
    import re

    src = Path(a.chapters).expanduser().resolve()
    video = Path(a.video).expanduser().resolve()
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = data.get("chapters") if isinstance(data, dict) else data
    if not rows:
        raise SystemExit(f"{src.name} 里没有 chapters。")
    meta = media.probe(video)
    items = []
    for r in rows:
        title = str(r.get("title", "")).strip()
        title = re.sub(r"^\d+[_\-\s]+", "", title)                     # "02_观点_xxx" → "观点_xxx"
        typ = str(r.get("type", "")).strip()
        if typ and title.startswith(typ + "_"):
            title = title[len(typ) + 1:]
        title = title.replace("_", " ").strip()
        items.append({"start": round(_secs(r["start_time"]), 2), "title": title,
                      "_end": round(_secs(r.get("end_time", 0)), 2)})
    items.sort(key=lambda c: c["start"])
    gaps = sum(1 for p, n in zip(items, items[1:]) if n["start"] - p["_end"] > 5)
    if items[0]["start"] < 15:
        items[0]["start"] = 0
    for c in items:
        c.pop("_end")
    plan = {"video": video.name if video.parent == plan_path_for(video).parent else str(video),
            "style": dict(DEFAULT_STYLE), "bar": {"style": "tabs", "position": "top", "announce": False},
            "chapters": items, "output": {"mode": "burn"}}
    pp = plan_path_for(video)
    if pp.exists() and not a.force:
        raise SystemExit(f"方案已存在：{pp}（覆盖加 --force）")
    pp.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已从 {src.name} 生成方案：{pp}（{len(items)} 章）")
    if data.get("mode") == "short-video" or gaps:
        print("提醒：这份切片是挑出来的精彩片段（short-video 模式），中间有跳过的部分，不是连续的章节。"
              "章节条需要覆盖全片：最好让 meeting-clipper 用 archive 模式（按议程切）重新出一份；"
              "或者在这份基础上补上被跳过的段落。")
    if meta["duration"] and items and items[-1]["start"] > meta["duration"]:
        print("提醒：章节时间超出了视频时长——这份 chapters.json 可能不是对应这个视频的。")
    print("下一步：切片标题通常偏长，把 chapters 里的 title 缩成 2–6 个字的名词短语，然后 check。")


def cmd_check(a):
    plan, pp, video = load(a.plan)
    meta = media.probe(video)
    errs, warns = validate(plan, meta)
    for w in warns:
        print("提醒：" + w)
    for e in errs:
        print("✗ " + e)
    if errs:
        sys.exit(2)
    _, ctx, els = build(plan, pp, video)
    bad = custom.smoke_test(els)
    for b in bad:
        print("✗ " + b)
    if bad:
        sys.exit(2)
    print(f"✓ 没问题：{len(els)} 个元素")
    for e in els:
        print(f"  {media.fmt_time(e.start)}–{media.fmt_time(e.end)}  {e.label}")
    print("下一步：`still` 出几帧看效果。")


def cmd_still(a):
    plan, pp, video = load(a.plan)
    meta, ctx, els = build(plan, pp, video)
    times = a.at or [t for t, _ in picks_for(els)][:4]
    work = work_for(video)
    work.mkdir(parents=True, exist_ok=True)
    for t in times:
        im = composite_still(els, media.frame(video, t, ctx.W, ctx.H), t)
        im.thumbnail((1600, 1600))
        out = work / f"still_{t:.1f}.jpg"
        im.save(out, quality=90)
        print(f"{media.fmt_time(t)} → {out}")
    print("下一步：看图检查（SKILL.md「检查清单」），没问题就 render。")


def cmd_render(a):
    from core import compose

    plan, pp, video = load(a.plan)
    meta = media.probe(video)
    errs, warns = validate(plan, meta)
    for w in warns:
        print("提醒：" + w)
    if errs:
        for e in errs:
            print("✗ " + e)
        sys.exit(2)
    meta, ctx, els = build(plan, pp, video)
    bad = custom.smoke_test(els)
    if bad:
        for b in bad:
            print("✗ " + b)
        sys.exit(2)
    mode = a.mode or (plan.get("output") or {}).get("mode", "burn")
    compose.produce(video, meta, ctx, els, mode, work_for(video), picks_for(els), plan["style"].get("sfx", True), "章节版")
    yt = youtube_txt(plan)
    if yt:
        f = video.parent / f"{video.stem}_YouTube章节.txt"
        f.write_text(yt, encoding="utf-8")
        print(f"YouTube 章节：{f}")
    print("下一步：看检查图，按检查清单过一遍；改了方案再 render 只会重画改动的部分。")


def main():
    ap = argparse.ArgumentParser(prog="chapters.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("look")
    p.add_argument("video")
    p.add_argument("--every", type=float, help="缩略图间隔秒数（默认按时长约 32 张）")
    p.add_argument("--grid", type=float, action="append", help="出这一秒带坐标网格的大图，可写多次")
    p.set_defaults(fn=cmd_look)
    p = sub.add_parser("init")
    p.add_argument("video")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("from-clipper", help="用 meeting-clipper 的 chapters.json 生成方案")
    p.add_argument("chapters", help="meeting-clipper 写的 <视频名>_chapters.json")
    p.add_argument("video", help="要加章节条的原视频")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_from_clipper)
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

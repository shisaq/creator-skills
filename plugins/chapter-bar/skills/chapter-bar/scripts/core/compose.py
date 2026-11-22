"""Elements → cached alpha clips → burned-in mp4 and/or transparent ProRes overlay, plus sound effects and a check sheet."""

from __future__ import annotations

import math
import platform
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import fonts, media
from .base import Ctx, Element, composite_still


# ----------------------------------------------------------------------------- sound effects (synthesised, no assets)
SR = 48000


def _env(n, a=0.003, d=0.15):
    t = np.arange(n) / SR
    return np.minimum(1, t / a) * np.exp(-t / d)


def _ding(f=1568, L=0.6):
    n = int(L * SR)
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2.01 * t) + 0.2 * np.sin(2 * np.pi * f * 3 * t)) / 1.6 * _env(n, 0.002, 0.18)


def _pop(f0=1200, f1=500, L=0.15):
    n = int(L * SR)
    t = np.arange(n) / SR
    f = f0 * (f1 / f0) ** (t / L)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.04)


def _whoosh(L=0.45):
    n = int(L * SR)
    x = np.random.default_rng(1).standard_normal(n)
    out = np.zeros(n)
    acc = 0.0
    for i in range(n):
        a = 0.02 + 0.25 * math.sin(math.pi * i / n)
        acc += a * (x[i] - acc)
        out[i] = acc
    return out * np.sin(np.pi * np.arange(n) / n) ** 2 * 1.4


SFX = {"ding": _ding, "pop": _pop, "whoosh": _whoosh}


def write_sfx(els, duration, out: Path) -> bool:
    events = [s for e in els for s in e.sfx]
    if not events:
        return False
    cache = {}
    track = np.zeros(int((duration + 2) * SR))
    for t, name, g in events:
        if name not in SFX:
            continue
        if name not in cache:
            cache[name] = SFX[name]()
        s = cache[name]
        o = max(0, int(t * SR))
        track[o:o + len(s)] += s[:max(0, len(track) - o)] * g
    pcm = (np.clip(track[: int(duration * SR)], -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    return True


# ----------------------------------------------------------------------------- clips
def write_clip(e: Element, fps: float, path: Path):
    w, h = e.size
    n = max(1, int(math.ceil((e.end - e.start) * fps)))
    tmp = path.with_suffix(".tmp.mov")
    p = subprocess.Popen([media.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}",
                          "-r", f"{fps:.5f}", "-i", "-", "-c:v", "qtrle", str(tmp)], stdin=subprocess.PIPE)
    try:
        for i in range(n):
            im = e.draw(e.start + i / fps)
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            if im.size != (w, h):
                im = im.resize((w, h))
            p.stdin.write(im.tobytes())
        p.stdin.close()
    except BrokenPipeError:
        pass
    if p.wait() != 0 or not tmp.exists():
        raise SystemExit(f"渲染「{e.label}」失败（ffmpeg 报错见上）。")
    tmp.replace(path)


def render_clips(ctx: Ctx, els: list[Element], clip_dir: Path):
    clip_dir.mkdir(parents=True, exist_ok=True)
    out, keep = [], set()
    for i, e in enumerate(els, 1):
        path = clip_dir / f"{e.kind}_{e.key()}.mov"
        keep.add(path.name)
        if path.exists():
            print(f"  [{i}/{len(els)}] {e.label}（{media.fmt_time(e.start)}）没改动，复用", flush=True)
        else:
            t0 = time.time()
            print(f"  [{i}/{len(els)}] {e.label}（{media.fmt_time(e.start)}–{media.fmt_time(e.end)}）…", end="", flush=True)
            write_clip(e, ctx.fps, path)
            print(f" {time.time() - t0:.0f}s", flush=True)
        out.append((e, path))
    for f in clip_dir.glob("*.mov"):
        if f.name not in keep:
            f.unlink(missing_ok=True)
    return out


# ----------------------------------------------------------------------------- compose
def _overlay_chain(base_label, clips, first_input):
    parts, cur = [], base_label
    for j, (e, _) in enumerate(clips):
        f = f"[{first_input + j}:v]"
        if e.scale != 1.0:
            f += f"scale={e.w}:{e.h}:flags=bilinear,"
        f += f"setpts=PTS-STARTPTS+{e.start:.3f}/TB[c{j}]"
        parts.append(f)
        parts.append(f"[{cur}][c{j}]overlay={e.x}:{e.y}:eof_action=pass[v{j}]")
        cur = f"v{j}"
    return parts, cur


def _encoder(meta):
    px = meta["width"] * meta["height"]
    if platform.system() == "Darwin" and "h264_videotoolbox" in media.encoders():
        br = 45 if px > 2560 * 1440 else (16 if px > 1280 * 720 else 8)
        return ["-c:v", "h264_videotoolbox", "-b:v", f"{br}M", "-maxrate", f"{int(br * 1.4)}M", "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]


def _run(args, duration, label):
    cmd = [media.ffmpeg(), "-hide_banner", "-v", "error", "-progress", "pipe:1", "-nostats", *args]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, errors="replace")
    last = 0.0
    for line in p.stdout:
        if line.startswith("out_time_us="):
            try:
                t = int(line.split("=")[1]) / 1e6
            except ValueError:
                continue
            if t - last >= max(10.0, duration / 10):
                print(f"  {label} {min(100, t / duration * 100):.0f}%", flush=True)
                last = t
    if p.wait() != 0:
        raise SystemExit(f"{label}失败（ffmpeg 报错见上）。")


def burn(video: Path, meta, clips, sfx: Path | None, out: Path):
    inputs = ["-i", str(video)]
    for _, path in clips:
        inputs += ["-i", str(path)]
    parts, last = _overlay_chain("0:v", clips, 1)
    parts.append(f"[{last}]format=yuv420p[vout]")
    amap = []
    if sfx:
        inputs += ["-i", str(sfx)]
        si = len(clips) + 1
        if meta["has_audio"]:
            parts.append(f"[{si}:a]aformat=channel_layouts=stereo[sf];[0:a][sf]amix=inputs=2:normalize=0:duration=first[aout]")
        else:
            parts.append(f"[{si}:a]aformat=channel_layouts=stereo[aout]")
        amap = ["-map", "[aout]"]
    elif meta["has_audio"]:
        amap = ["-map", "0:a:0"]
    _run(["-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[vout]", *amap, *_encoder(meta),
          "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-t", f"{meta['duration']:.3f}", str(out)],
         meta["duration"], "合成成片")


def overlay(ctx: Ctx, clips, sfx: Path | None, out: Path):
    D = ctx.duration
    inputs = ["-f", "lavfi", "-i", f"color=c=black@0.0:s={ctx.W}x{ctx.H}:r={ctx.fps:.5f}:d={D:.3f},format=rgba"]
    for _, path in clips:
        inputs += ["-i", str(path)]
    parts, last = _overlay_chain("0:v", clips, 1)
    parts.append(f"[{last}]format=yuva444p10le[vout]")
    amap, acodec = [], []
    if sfx:
        inputs += ["-i", str(sfx)]
        amap, acodec = ["-map", f"{len(clips) + 1}:a"], ["-c:a", "pcm_s16le"]
    _run(["-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[vout]", *amap, "-c:v", "prores_ks",
          "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "8", *acodec, "-t", f"{D:.3f}", str(out)],
         D, "导出透明叠加层")


# ----------------------------------------------------------------------------- check sheet
def sheet(ctx: Ctx, els, picks: list[tuple[float, str]], out: Path, rendered: Path | None, source: Path):
    """Grid of frames with captions. Frames come from the rendered video if given, else are composited from source."""
    picks = sorted(picks)[:16]
    if not picks:
        return None
    tw = 480 if not ctx.portrait else 300
    th = int(tw * ctx.H / ctx.W)
    cols = 4 if len(picks) > 2 else len(picks)
    rows = math.ceil(len(picks) / cols)
    cap = 34
    grid = Image.new("RGB", (cols * tw, rows * (th + cap)), (20, 20, 20))
    d = ImageDraw.Draw(grid)
    font = fonts.get("ui", 18, ctx.font_ui, ctx.font_title)
    for i, (t, label) in enumerate(picks):
        t = min(max(0.0, t), ctx.duration - 0.05)
        if rendered is not None:
            im = media.frame(rendered, t, tw, th)
        else:
            im = composite_still(els, media.frame(source, t, ctx.W, ctx.H), t).resize((tw, th))
        x, y = (i % cols) * tw, (i // cols) * (th + cap)
        grid.paste(im, (x, y))
        d.text((x + 8, y + th + 6), f"{media.fmt_time(t)}  {label}"[:30], font=font, fill=(240, 240, 240))
    grid.save(out, quality=88)
    return out


def produce(video: Path, meta, ctx: Ctx, els, mode: str, work: Path, picks, sfx_on=True, suffix="点缀版"):
    """Render clips, mix sound effects, write outputs and a check sheet. Returns list of output paths."""
    t0 = time.time()
    print(f"视频 {meta['width']}x{meta['height']} {meta['duration']:.1f}s；{len(els)} 个效果：", flush=True)
    clips = render_clips(ctx, els, work / "clips")
    sfx = work / "sfx.wav"
    has_sfx = sfx_on and write_sfx(els, meta["duration"], sfx)
    outs = []
    if mode in ("burn", "both"):
        out = video.parent / f"{video.stem}_{suffix}.mp4"
        burn(video, meta, clips, sfx if has_sfx else None, out)
        got = media.probe(out)
        ok = abs(got["duration"] - meta["duration"]) < 0.25
        print(f"成片：{out}（{got['duration']:.1f}s{'' if ok else '，⚠ 时长和原片不一致'}）")
        outs.append(out)
    if mode in ("overlay", "both"):
        out = video.parent / f"{video.stem}_叠加层.mov"
        overlay(ctx, clips, sfx if has_sfx else None, out)
        print(f"透明叠加层：{out}（ProRes 4444 带透明通道{'，含音效轨' if has_sfx else ''}；放原片上方一轨，0 秒对齐）")
        outs.append(out)
    burned = next((o for o in outs if o.suffix == ".mp4"), None)
    sh = sheet(ctx, els, picks, video.parent / f"{video.stem}_检查图.jpg", burned, video)
    print(f"用时 {time.time() - t0:.0f}s")
    if sh:
        print(f"检查图：{sh}")
    return outs

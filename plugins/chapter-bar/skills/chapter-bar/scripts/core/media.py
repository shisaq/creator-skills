"""ffmpeg discovery, probing, frame/audio extraction. No ffprobe needed (imageio-ffmpeg doesn't ship it)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

_FF: str | None = None


def ffmpeg() -> str:
    """VA_FFMPEG env > imageio-ffmpeg's bundled binary (known to have qtrle/prores_ks/libx264) > ffmpeg on PATH."""
    global _FF
    if _FF:
        return _FF
    env = os.environ.get("VA_FFMPEG")
    if env:
        _FF = env
        return _FF
    try:
        import imageio_ffmpeg  # type: ignore

        _FF = imageio_ffmpeg.get_ffmpeg_exe()
        return _FF
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        _FF = found
        return _FF
    raise SystemExit(
        "找不到 ffmpeg。请用 `uv run accents.py ...` 运行（会自动带上 ffmpeg）；"
        "或自己安装 ffmpeg（macOS: brew install ffmpeg；Windows: winget install Gyan.FFmpeg）。"
    )


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run([ffmpeg(), "-hide_banner", *args], **kw)


def encoders() -> set[str]:
    out = run(["-encoders"], capture_output=True, text=True, errors="replace").stdout
    names = set()
    for line in out.splitlines():
        m = re.match(r"\s*[VAS][.\w]{5}\s+(\S+)", line)
        if m:
            names.add(m.group(1))
    return names


def probe(video: str | Path) -> dict:
    """Parse ffmpeg's banner. Width/height are the *displayed* size (rotation applied, as ffmpeg autorotates)."""
    p = run(["-i", str(video)], capture_output=True, text=True, errors="replace")
    err = p.stderr
    if "No such file" in err or "Invalid data" in err:
        raise SystemExit(f"读不了这个视频：{video}\n{err.strip().splitlines()[-1] if err.strip() else ''}")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if not m:
        raise SystemExit(f"读不出视频时长：{video}")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    vline = next((l for l in err.splitlines() if re.search(r"Stream #.*Video:", l) and "attached pic" not in l), None)
    if not vline:
        raise SystemExit(f"这个文件里没有视频画面：{video}")
    sm = re.search(r"\b(\d{2,5})x(\d{2,5})\b", vline)
    w, h = int(sm.group(1)), int(sm.group(2))
    fm = re.search(r"([\d.]+) fps", vline) or re.search(r"([\d.]+) tbr", vline)
    fps = float(fm.group(1)) if fm else 30.0
    rot = 0.0
    rm = re.search(r"rotation of (-?[\d.]+) degrees", err) or re.search(r"rotate\s*:\s*(-?\d+)", err)
    if rm:
        rot = float(rm.group(1))
    if int(round(abs(rot))) % 180 == 90:
        w, h = h, w
    hdr = bool(re.search(r"arib-std-b67|smpte2084|bt2020", vline))
    return {
        "path": str(Path(video).resolve()),
        "duration": round(duration, 3),
        "width": w,
        "height": h,
        "fps": fps,
        "has_audio": bool(re.search(r"Stream #.*Audio:", err)),
        "hdr": hdr,
    }


def frame(video: str | Path, t: float, width: int, height: int):
    """One RGB frame at time t, scaled to width x height, as a PIL image."""
    from PIL import Image

    p = run(
        ["-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    data = p.stdout
    if len(data) < width * height * 3:  # past the end: grab the last frame instead
        p = run(["-v", "error", "-sseof", "-0.2", "-i", str(video), "-frames:v", "1",
                 "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
        data = p.stdout
    if len(data) < width * height * 3:
        return Image.new("RGB", (width, height), (40, 40, 40))
    return Image.frombytes("RGB", (width, height), data[: width * height * 3])


def audio_mono(video: str | Path, sr: int = 22050) -> np.ndarray:
    p = run(["-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def make_proxy(video: str | Path, out: Path, long_side: int = 1280) -> Path:
    """Small H.264 copy that every browser can play and seek (iPhone HEVC/MOV often can't)."""
    if out.exists() and out.stat().st_mtime >= Path(video).stat().st_mtime and out.stat().st_size > 0:
        return out
    meta = probe(video)
    if meta["width"] >= meta["height"]:
        vf = f"scale='min({long_side},iw)':-2"
    else:
        vf = f"scale=-2:'min({long_side},ih)'"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.mp4")
    print(f"正在生成网页预览用的小视频（只做一次，长视频要一两分钟）：{out.name}", flush=True)
    args = ["-v", "error", "-y", "-i", str(video), "-vf", vf + ",format=yuv420p", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "27", "-g", "30", "-movflags", "+faststart"]
    args += ["-c:a", "aac", "-b:a", "128k"] if meta["has_audio"] else ["-an"]
    p = run(args + [str(tmp)])
    if p.returncode != 0 or not tmp.exists():
        raise SystemExit("预览小视频生成失败（ffmpeg 报错见上）。")
    tmp.replace(out)
    return out


def fmt_time(t: float) -> str:
    t = max(0, int(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy", "imageio-ffmpeg>=0.5"]
# ///
"""Rough cut from a cut plan: drop whole sentences, tighten pauses, write a source-linked FCPXML.

The cut plan names what to remove by its words, not by timecodes, so cuts land between characters:

    {"remove": [{"text": "今天在打篮球正好就想到", "why": "flat opener"},
                {"text": "那当然有一些比较有趣的点我觉得可能是这个比喻背后也有的考虑", "why": "filler"},
                {"text": "嗯", "near": 12.1, "why": "filler"},          # near = seconds, for short/repeated words
                {"from": 152.5, "to": 163.4, "why": "tail"}],          # seconds also work
     "pause": {"max": 0.3, "keep": 0.15}}                                # optional

    uv run roughcut.py <video> <video>.words.json cutplan.json [--out DIR] [--preview]

Writes <stem>_粗剪.fcpxml (+ _剪辑点.md, and _粗剪预览.mp4 with --preview). No zoom, no effects:
the editor refines in Final Cut Pro, where every clip still points at the original file.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import urllib.parse
from fractions import Fraction
from pathlib import Path

PUN = re.compile(r"[\s，。！？；、,.!?;：:“”\"'（）()…—-]")


def ffmpeg():
    f = shutil.which("ffmpeg")
    if f:
        return f
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffprobe_json(path: Path) -> dict:
    fp = shutil.which("ffprobe")
    if not fp:
        raise SystemExit("ffprobe not found (install ffmpeg).")
    out = subprocess.run([fp, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def rms_db(path: Path, hop=0.02):
    import numpy as np
    raw = subprocess.run([ffmpeg(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    n = int(len(x) / 16000 / hop)
    fr = x[: n * int(16000 * hop)].reshape(n, -1)
    return 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9), hop


# --------------------------------------------------------------------------- plan → keep ranges

def locate(tokens, text, used, near=None):
    """Index range [i, j] of the tokens spelling `text` (punctuation ignored).

    Takes the first unused match, or the one starting closest to `near` (seconds) when given:
    use `near` for short or repeated words such as a filler "嗯"."""
    stream = "".join(PUN.sub("", t["t"]) for t in tokens)
    owner = []
    for i, t in enumerate(tokens):
        owner += [i] * len(PUN.sub("", t["t"]))
    want = PUN.sub("", text)
    if not want:
        return None
    hits, start = [], 0
    while True:
        k = stream.find(want, start)
        if k < 0:
            break
        i, j = owner[k], owner[k + len(want) - 1]
        if not any(a <= i <= b or a <= j <= b for a, b in used):
            hits.append((i, j))
        start = k + 1
    if not hits:
        return None
    if near is None:
        return hits[0]
    return min(hits, key=lambda h: abs(tokens[h[0]]["s"] - float(near)))


def quietest(db, hop, a, b):
    """Time of the quietest 20 ms frame in [a, b] (falls back to the midpoint)."""
    i0, i1 = max(0, int(a / hop)), min(len(db) - 1, int(b / hop))
    if i1 <= i0:
        return (a + b) / 2
    k = min(range(i0, i1 + 1), key=lambda i: db[i])
    return k * hop + hop / 2


def plan_keeps(tokens, plan, dur, db, hop):
    removes, used, misses = [], [], []
    for r in plan.get("remove", []):
        if "text" in r:
            hit = locate(tokens, r["text"], used, r.get("near"))
            if not hit:
                misses.append(r["text"])
                continue
            i, j = hit
            used.append(hit)
            prev_e = tokens[i - 1]["e"] if i > 0 else 0.0
            next_s = tokens[j + 1]["s"] if j + 1 < len(tokens) else dur
            a = 0.0 if i == 0 else quietest(db, hop, prev_e - 0.04, tokens[i]["s"] + 0.06)
            b = dur if j + 1 >= len(tokens) else quietest(db, hop, tokens[j]["e"] - 0.06, next_s + 0.04)
            removes.append((a, b, r.get("why", ""), r["text"]))
        else:
            removes.append((float(r["from"]), float(r["to"]), r.get("why", ""), r.get("text", "")))
    removes.sort()
    keeps, t = [], 0.0
    for a, b, *_ in removes:
        if a > t + 0.05:
            keeps.append([t, a])
        t = max(t, b)
    if dur - t > 0.05:
        keeps.append([t, dur])
    return keeps, removes, misses


def tighten(keeps, db, hop, max_pause=0.3, keep_pause=0.15, thresh=None):
    """Split keep ranges at long silences, leaving `keep_pause` of air."""
    import numpy as np
    if thresh is None:  # speech/noise split from this file's own level distribution
        thresh = float(np.percentile(db, 20)) + 6
    segs = []
    for a, b in keeps:
        cur = a
        i0, i1 = int(a / hop), int(b / hop)
        k = i0
        while k < i1:
            if db[k] < thresh:
                m = k
                while m < i1 and db[m] < thresh:
                    m += 1
                s, e = k * hop, m * hop
                if e - s >= max_pause and s > a + 0.05 and e < b - 0.05:
                    head = keep_pause * 0.55
                    segs.append([cur, s + head, True])
                    cur = e - (keep_pause - head)
                k = m
            else:
                k += 1
        segs.append([cur, b, False])
    return [(round(s, 3), round(e, 3)) for s, e, _ in segs]


# --------------------------------------------------------------------------- FCPXML

def colorspace(v):
    t, p = v.get("color_transfer", ""), v.get("color_primaries", "")
    if t == "arib-std-b67":
        return "9-18-9 (Rec. 2020 HLG)"
    if t == "smpte2084":
        return "9-16-9 (Rec. 2020 PQ)"
    if p == "bt2020":
        return "9-1-9 (Rec. 2020)"
    return "1-1-1 (Rec. 709)"


def frame_dur(rate: Fraction) -> Fraction:
    table = {Fraction(30000, 1001): Fraction(1001, 30000), Fraction(60000, 1001): Fraction(1001, 60000),
             Fraction(24000, 1001): Fraction(1001, 24000)}
    if rate in table:
        return table[rate]
    r = round(float(rate))
    return Fraction(100, r * 100) if r else Fraction(1, 30)


def rt(x: Fraction) -> str:
    x = Fraction(x)
    return "0s" if x == 0 else f"{x.numerator}/{x.denominator}s"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def fcpxml(video: Path, segs, info, seams, title):
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    has_a = any(s["codec_type"] == "audio" for s in info["streams"])
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
    rate = Fraction(v.get("r_frame_rate", "30/1"))
    if rate > 120 or rate <= 0:
        rate = Fraction(v.get("avg_frame_rate", "30/1")).limit_denominator(1001)
    fd = frame_dur(rate)
    W, H = int(v["width"]), int(v["height"])
    rot = int((v.get("tags") or {}).get("rotate", 0) or 0)
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if abs(rot) in (90, 270):
        W, H = H, W
    if v.get("duration_ts") and v.get("time_base"):
        adur = Fraction(int(v["duration_ts"])) * Fraction(v["time_base"])
    else:
        adur = Fraction(str(info["format"]["duration"]))
    frames_total = int(adur / fd)
    snap = lambda t: int(round(Fraction(str(t)) / fd))  # noqa: E731
    url = "file://" + urllib.parse.quote(str(video))
    clips, off = [], 0
    seam_set = set(seams)
    for n, (s, e) in enumerate(segs):
        fa, fb = snap(s), min(snap(e), frames_total)
        if fb <= fa:
            continue
        mk = ""
        if n in seam_set:
            mk = f'<marker start="{rt(fa * fd)}" duration="{rt(fd)}" value="{esc(seams[n])}"/>'
        clips.append(f'<asset-clip ref="r3" offset="{rt(off * fd)}" name="{n + 1:02d}" start="{rt(fa * fd)}" '
                     f'duration="{rt((fb - fa) * fd)}" format="r2" tcFormat="NDF" audioRole="dialogue">{mk}</asset-clip>')
        off += fb - fa
    audio = (f' hasAudio="1" audioSources="1" audioChannels="{a.get("channels", 2)}" '
             f'audioRate="{a.get("sample_rate", 48000)}"') if has_a else ""
    body = "\n".join("            " + c for c in clips)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.11">
  <resources>
    <format id="r1" name="FFVideoFormatRateUndefined" frameDuration="{rt(fd)}" width="{W}" height="{H}" colorSpace="1-1-1 (Rec. 709)"/>
    <format id="r2" name="FFVideoFormatRateUndefined" width="{W}" height="{H}" colorSpace="{colorspace(v)}"/>
    <asset id="r3" name="{esc(video.stem)}" start="0s" duration="{rt(adur)}" hasVideo="1" format="r2" videoSources="1"{audio}>
      <media-rep kind="original-media" src="{url}"/>
    </asset>
  </resources>
  <library>
    <event name="{esc(title)}">
      <project name="{esc(title)}">
        <sequence format="r1" duration="{rt(off * fd)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">
          <spine>
{body}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
''', off * float(fd)


def preview(video: Path, segs, out: Path):
    n = len(segs)
    f = [f"[0:v]split={n}" + "".join(f"[v{i}]" for i in range(n)),
         f"[0:a]asplit={n}" + "".join(f"[a{i}]" for i in range(n))]
    for i, (s, e) in enumerate(segs):
        d = e - s
        f.append(f"[v{i}]trim={s}:{e},setpts=PTS-STARTPTS[V{i}]")
        f.append(f"[a{i}]atrim={s}:{e},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,afade=t=out:st={max(0, d - 0.012):.3f}:d=0.012[A{i}]")
    f.append("".join(f"[V{i}][A{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]")
    script = out.with_suffix(".filter.txt")
    script.write_text(";\n".join(f), encoding="utf-8")
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(video), "-filter_complex_script", str(script),
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)], check=True)
    script.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("words")
    ap.add_argument("plan")
    ap.add_argument("--out")
    ap.add_argument("--preview", action="store_true", help="Also render a quick MP4 of the cut (no zoom).")
    a = ap.parse_args()
    video = Path(a.video).expanduser().resolve()
    W = json.loads(Path(a.words).read_text(encoding="utf-8"))
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    info = ffprobe_json(video)
    dur = float(info["format"]["duration"])
    db, hop = rms_db(video)
    keeps, removes, misses = plan_keeps(W["tokens"], plan, dur, db, hop)
    if misses:
        print("Could not find these removals in the transcript (check the wording):")
        for m in misses:
            print("  -", m)
    p = plan.get("pause", {})
    segs = tighten(keeps, db, hop, p.get("max", 0.3), p.get("keep", 0.15))
    # seams = first segment after each content cut
    seams, acc = {}, 0
    for k, (ka, kb) in enumerate(keeps):
        if k > 0:
            idx = next(i for i, (s, e) in enumerate(segs) if abs(s - ka) < 1e-3 or (s >= ka - 1e-3 and s < kb))
            gone = [r for r in removes if abs(r[1] - ka) < 0.05]
            label = gone[0][3][:14] if gone and gone[0][3] else "content cut"
            seams[idx] = f"删句接缝：{label}"
    out = Path(a.out).expanduser() if a.out else video.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = video.stem
    xml, total = fcpxml(video, segs, info, seams, f"{stem}_粗剪")
    (out / f"{stem}_粗剪.fcpxml").write_text(xml, encoding="utf-8")
    lines = [f"# 剪辑点 — {video.name}", "", f"原片 {dur:.1f}s → 粗剪 {total:.1f}s，{len(segs)} 段", "", "## 删掉的内容", ""]
    for s, e, why, text in removes:
        lines.append(f"- {s:7.2f}–{e:7.2f}  {text[:40]}  （{why}）")
    lines += ["", "## 片段（成片时间 ← 原片区间）", ""]
    t = 0.0
    for i, (s, e) in enumerate(segs):
        lines.append(f"{i + 1:02d}  {t:7.2f}  ←  {s:7.2f}–{e:7.2f}" + ("   ◆ 接缝" if i in seams else ""))
        t += e - s
    (out / f"{stem}_剪辑点.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{dur:.1f}s → {total:.1f}s, {len(segs)} clips, {len(seams)} content seams")
    print(out / f"{stem}_粗剪.fcpxml")
    if a.preview:
        pv = out / f"{stem}_粗剪预览.mp4"
        preview(video, segs, pv)
        print(pv)


if __name__ == "__main__":
    main()

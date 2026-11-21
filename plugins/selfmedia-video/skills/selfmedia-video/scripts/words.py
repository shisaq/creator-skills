#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["sherpa-onnx>=1.10.0", "numpy", "imageio-ffmpeg>=0.5"]
# ///
"""Character-level transcript of a talking-head video: every character with its start/end time.

Cut points, caption timing and the cut plan all need per-character times, not subtitle lines.

Backends (first that works):
  funasr  - a self-hosted "subtitle studio" service (FunASR Paraformer with hotwords), if
            $SELFMEDIA_FUNASR_URL is set. Uploads the file, waits, then reads GET /api/projects/<id>/tokens.
  local   - sherpa-onnx + SenseVoice on this machine (same model cache as the other creator-skills).

    uv run words.py <video> [--terms "英伟达,黄仁勋"] [--backend auto|funasr|local] [--out DIR]

Writes next to the video (or into --out):
  <stem>.words.json      {"backend", "duration", "tokens": [{"t", "s", "e", "p", "gap"}]}  (seconds)
  <stem>.transcript.md   one sentence per line with [start-end] times: what the cut plan is written from
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

PUNCT = set("，。！？；、,.!?;：:")


# --------------------------------------------------------------------------- funasr service

def funasr(video: Path, base: str, terms: str | None) -> list[dict]:
    base = base.rstrip("/")
    q = {"name": video.name}
    if terms:
        q["terms"] = terms
    size = video.stat().st_size
    print(f"Uploading to {base} ({size >> 20} MB) ...", flush=True)
    with video.open("rb") as fh:
        req = urllib.request.Request(f"{base}/api/upload?{urllib.parse.urlencode(q)}", data=fh, method="PUT")
        req.add_header("Content-Length", str(size))
        req.add_header("Content-Type", "application/octet-stream")
        with urllib.request.urlopen(req, timeout=900) as r:
            pid = json.loads(r.read())["id"]
    last = None
    while True:
        with urllib.request.urlopen(f"{base}/api/projects/{pid}", timeout=30) as r:
            p = json.loads(r.read())
        if p["status"] == "ready":
            break
        if p["status"] == "error":
            raise RuntimeError(f"FunASR failed: {p.get('error')}")
        if p["status"] != last:
            print(f"  {p['status']} ...", flush=True)
            last = p["status"]
        time.sleep(3)
    with urllib.request.urlopen(f"{base}/api/projects/{pid}/tokens", timeout=60) as r:
        raw = json.loads(r.read())
    print(f"FunASR project: {base}/p/{pid}", flush=True)
    return [{"t": t["t"], "p": t.get("p", ""), "s": t["s"] / 1000, "e": t["e"] / 1000,
             "gap": float(t.get("gap", 0.0))} for t in raw]


# --------------------------------------------------------------------------- local SenseVoice

def local(video: Path, language: str) -> list[dict]:
    import numpy as np
    import sherpa_onnx  # type: ignore
    import transcribe as T  # the shared creator-skills transcriber (same models, same cache)

    models = T.ensure_models(T.model_root(None))
    samples = T.load_audio(video)
    sr = T.SAMPLE_RATE
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(models["sense-voice/model.int8.onnx"]), tokens=str(models["sense-voice/tokens.txt"]),
        num_threads=max(1, min(8, (os.cpu_count() or 4) - 1)), use_itn=True,
        language="" if language == "auto" else language)
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(models["silero_vad.onnx"])
    cfg.silero_vad.min_silence_duration = 0.25
    cfg.silero_vad.min_speech_duration = 0.2
    try:
        cfg.silero_vad.max_speech_duration = 12
    except Exception:
        pass
    cfg.sample_rate = sr
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)
    win = cfg.silero_vad.window_size
    toks: list[dict] = []

    def drain():
        while not vad.empty():
            seg = vad.front
            st = seg.start / sr
            en = st + len(seg.samples) / sr
            s = rec.create_stream()
            s.accept_waveform(sr, seg.samples)
            rec.decode_stream(s)
            res = s.result
            pieces = [p.replace("▁", " ").strip() for p in (res.tokens or [])]
            stamps = list(res.timestamps or [])
            if len(stamps) != len(pieces):
                stamps = [i * (en - st) / max(1, len(pieces)) for i in range(len(pieces))]
            seg_toks = []
            for i, (p, ts) in enumerate(zip(pieces, stamps)):
                if not p:
                    continue
                if all(c in PUNCT for c in p):
                    if seg_toks:
                        seg_toks[-1]["p"] += p
                    continue
                nxt = st + stamps[i + 1] if i + 1 < len(stamps) else en
                seg_toks.append({"t": p, "p": "", "s": st + ts, "e": min(nxt, en), "gap": 0.0})
            if seg_toks:
                seg_toks[-1]["gap"] = 0.3
            toks.extend(seg_toks)
            vad.pop()

    for i in range(0, len(samples) - win + 1, win):
        vad.accept_waveform(samples[i:i + win])
        drain()
    vad.flush()
    drain()
    # pauses between VAD segments
    for a, b in zip(toks, toks[1:]):
        a["gap"] = max(a["gap"], round(b["s"] - a["e"], 3))
    _ = np
    return toks


# --------------------------------------------------------------------------- outputs

def sentences(tokens: list[dict], pause: float = 0.35) -> list[dict]:
    out, cur = [], []
    for t in tokens:
        cur.append(t)
        if t["p"] and t["p"][-1] in "。！？!?；;" or t["gap"] >= pause or (t["p"] and len(cur) >= 14):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"s": c[0]["s"], "e": c[-1]["e"], "text": "".join(x["t"] + x["p"] for x in c)} for c in out]


def main():
    ap = argparse.ArgumentParser(description="Per-character transcript (FunASR service or local SenseVoice).")
    ap.add_argument("video")
    ap.add_argument("--terms", help="Comma-separated names to bias recognition (FunASR hotwords).")
    ap.add_argument("--backend", default="auto", choices=["auto", "funasr", "local"])
    ap.add_argument("--language", default="zh", choices=["auto", "zh", "en", "yue"])
    ap.add_argument("--out", help="Output directory (default: next to the video).")
    a = ap.parse_args()
    video = Path(a.video).expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"File not found: {video}")
    url = os.environ.get("SELFMEDIA_FUNASR_URL", "").strip()
    tokens, backend = None, None
    if a.backend in ("auto", "funasr") and url:
        try:
            tokens, backend = funasr(video, url, a.terms), "funasr"
        except Exception as e:  # noqa: BLE001
            if a.backend == "funasr":
                raise SystemExit(f"FunASR service failed: {e}")
            print(f"FunASR service unavailable ({e}); falling back to local SenseVoice.", flush=True)
    elif a.backend == "funasr":
        raise SystemExit("Set SELFMEDIA_FUNASR_URL to use the FunASR backend.")
    if tokens is None:
        tokens, backend = local(video, a.language), "local"
    out = Path(a.out).expanduser() if a.out else video.parent
    out.mkdir(parents=True, exist_ok=True)
    dur = tokens[-1]["e"] if tokens else 0
    wj = out / f"{video.stem}.words.json"
    wj.write_text(json.dumps({"source": str(video), "backend": backend, "duration": dur, "tokens": tokens},
                             ensure_ascii=False), encoding="utf-8")
    md = out / f"{video.stem}.transcript.md"
    lines = [f"# Transcript ({backend}) — {video.name}", "",
             "One sentence per line, [start–end] in seconds. Write the cut plan from this.", ""]
    lines += [f"[{s['s']:7.2f}–{s['e']:7.2f}] {s['text']}" for s in sentences(tokens)]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(tokens)} characters via {backend}\n  {wj}\n  {md}")


if __name__ == "__main__":
    main()

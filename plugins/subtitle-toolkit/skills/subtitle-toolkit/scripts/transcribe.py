#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["sherpa-onnx>=1.10.0", "numpy", "imageio-ffmpeg>=0.5"]
# ///
"""Transcribe a video/audio file into a timestamped SRT, fully local and cross-platform.

Engine: sherpa-onnx (onnxruntime, no PyTorch) running SenseVoice (zh/en/ja/ko/yue,
with punctuation) on speech segments cut by Silero VAD. Models (~240MB) download
once to ~/.cache/creator-skills/models, trying a China-friendly mirror first
(set MEETING_CLIPPER_REGION=global outside China to try HuggingFace first).

    uv run transcribe.py <video> [--language zh] [--max-chars 18] [--reading-copy]

Outputs next to the input (or at --output base):
    <stem>_转写.srt             subtitles, one line per ~max-chars characters
    <stem>_转写.segments.json   same content, structured
    <stem>_转写_阅读版.md       (with --reading-copy) ~25s paragraphs for reading

This file is self-contained and shared verbatim by several creator-skills plugins.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

SAMPLE_RATE = 16000
SV_REPO = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
MS_REPO = "https://www.modelscope.cn/models/pengzhendong/sherpa-onnx-sense-voice-zh-en-ja-ko-yue/resolve/master"
MODEL_SOURCES = {
    "sense-voice/model.int8.onnx": [
        f"{MS_REPO}/model.int8.onnx",
        f"https://hf-mirror.com/csukuangfj/{SV_REPO}/resolve/main/model.int8.onnx",
        f"https://huggingface.co/csukuangfj/{SV_REPO}/resolve/main/model.int8.onnx",
    ],
    "sense-voice/tokens.txt": [
        f"{MS_REPO}/tokens.txt",
        f"https://hf-mirror.com/csukuangfj/{SV_REPO}/resolve/main/tokens.txt",
        f"https://huggingface.co/csukuangfj/{SV_REPO}/resolve/main/tokens.txt",
    ],
    "silero_vad.onnx": [
        "https://hf-mirror.com/csukuangfj/vad/resolve/main/silero_vad.onnx",
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
        "https://huggingface.co/csukuangfj/vad/resolve/main/silero_vad.onnx",
    ],
}
MIN_SIZES = {"sense-voice/model.int8.onnx": 100_000_000, "sense-voice/tokens.txt": 100_000,
             "silero_vad.onnx": 300_000}
PUNCT = set("，。！？；、,.!?;")


# --------------------------------------------------------------------------- helpers


def ffmpeg_exe() -> str:
    env = os.environ.get("MEETING_CLIPPER_FFMPEG")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise SystemExit("找不到 ffmpeg。请用 `uv run` 运行本脚本（会自动带上 ffmpeg），或安装 ffmpeg。")


def format_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}:{int(seconds % 60):02d}"


def format_srt_time(seconds: float) -> str:
    ms_total = int(round(max(0.0, float(seconds)) * 1000))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list[dict], output: Path) -> None:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines += [str(i), f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}",
                  str(seg["text"]).strip(), ""]
    output.write_text("\n".join(lines), encoding="utf-8")


def is_cjk(text: str) -> bool:
    return sum(1 for ch in text if "一" <= ch <= "鿿") > len(text) * 0.3


def write_reading_copy(segments: list[dict], output: Path, block_seconds: float = 25.0) -> int:
    """Merge short subtitle lines into ~25s paragraphs: far cheaper to read than the SRT."""
    blocks: list[tuple[float, list[str]]] = []
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        if not blocks or seg["start"] - blocks[-1][0] >= block_seconds:
            blocks.append((seg["start"], []))
        blocks[-1][1].append(text)
    with output.open("w", encoding="utf-8") as fh:
        fh.write("# 文字稿（阅读版，约每 25 秒一段；精确时间以 SRT 为准）\n\n")
        for start, parts in blocks:
            joined = "".join(parts) if is_cjk("".join(parts)) else " ".join(parts)
            fh.write(f"[{format_time(start)}] {joined}\n\n")
    return len(blocks)


# --------------------------------------------------------------------------- models


def model_root(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    default = Path.home() / ".cache" / "creator-skills" / "models"
    return Path(os.environ.get("CREATOR_SKILLS_MODELS") or os.environ.get("MEETING_CLIPPER_MODELS") or default)


def download(urls: list[str], dest: Path, min_size: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    last_err = ""
    for url in urls:
        try:
            print(f"Downloading {dest.name} from {url.split('/')[2]} ...", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "creator-skills/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp, tmp.open("wb") as fh:
                total = int(resp.headers.get("Content-Length") or 0)
                done, last_pct = 0, -10
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if total and done * 100 // total >= last_pct + 10:
                        last_pct = done * 100 // total
                        print(f"  {last_pct}% ({done >> 20}MB / {total >> 20}MB)", flush=True)
            if tmp.stat().st_size < min_size:
                raise OSError(f"file too small ({tmp.stat().st_size} bytes), probably an error page")
            tmp.replace(dest)
            return
        except Exception as exc:
            last_err = f"{url}: {exc}"
            print(f"  failed: {exc}", flush=True)
            tmp.unlink(missing_ok=True)
    raise SystemExit(f"模型下载失败：{dest.name}\n最后错误：{last_err}\n"
                     f"可以手动下载后放到：{dest}\n候选地址：\n  " + "\n  ".join(urls))


def ensure_models(root: Path) -> dict[str, Path]:
    global_first = os.environ.get("MEETING_CLIPPER_REGION", "").lower() == "global"
    paths = {}
    for rel, urls in MODEL_SOURCES.items():
        if global_first:
            urls = sorted(urls, key=lambda u: ("modelscope" in u or "hf-mirror" in u))
        dest = root / rel
        if not dest.exists() or dest.stat().st_size < MIN_SIZES[rel]:
            download(urls, dest, MIN_SIZES[rel])
        paths[rel] = dest
    return paths


# --------------------------------------------------------------------------- recognition


def load_audio(media: Path):
    """Decode to 16 kHz mono float32 via ffmpeg, straight into memory (no temp wav)."""
    import numpy as np

    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(media),
           "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise SystemExit(f"音频解码失败：{proc.stderr.decode('utf-8', 'replace')[-800:]}")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def split_lines(text: str, tokens: list[str], stamps: list[float], seg_start: float, seg_end: float,
                max_chars: int) -> list[dict]:
    """Break one VAD segment into subtitle-sized lines at punctuation, using token timestamps."""
    if len(text) <= max_chars or not tokens or len(tokens) != len(stamps):
        return [{"start": seg_start, "end": seg_end, "text": text}]
    lines, buf, line_start = [], "", None
    for i, (tok, ts) in enumerate(zip(tokens, stamps)):
        piece = tok.replace("▁", " ")
        if line_start is None:
            line_start = seg_start + ts
            piece = piece.lstrip()
        buf += piece
        stripped = tok.strip()
        at_punct = bool(stripped) and stripped[-1] in PUNCT
        if (at_punct and len(buf) >= max_chars // 2) or len(buf) >= max_chars:
            end = seg_start + stamps[i + 1] if i + 1 < len(stamps) else seg_end
            lines.append({"start": line_start, "end": max(end, line_start + 0.3), "text": buf.strip()})
            buf, line_start = "", None
    if buf.strip():
        lines.append({"start": line_start if line_start is not None else seg_start, "end": seg_end,
                      "text": buf.strip()})
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Local transcription (sherpa-onnx + SenseVoice).")
    ap.add_argument("media", nargs="?", help="Video or audio file.")
    ap.add_argument("--language", default="auto", choices=["auto", "zh", "en", "ja", "ko", "yue"],
                    help="auto handles mixed Chinese/English; set zh/en when monolingual.")
    ap.add_argument("--threads", type=int, default=max(1, min(8, (os.cpu_count() or 4) - 1)))
    ap.add_argument("--model-dir", help="Model directory (default ~/.cache/creator-skills/models).")
    ap.add_argument("--max-chars", type=int, default=28,
                    help="Approx max characters per subtitle line (on-screen subtitles: ~16-20).")
    ap.add_argument("--output", help="Output base path without extension (default <stem>_转写).")
    ap.add_argument("--reading-copy", action="store_true", help="Also write a ~25s-paragraph reading copy.")
    ap.add_argument("--download-only", action="store_true", help="Just fetch the models and exit.")
    args = ap.parse_args()

    import sherpa_onnx  # type: ignore

    models = ensure_models(model_root(args.model_dir))
    if args.download_only:
        print("Models ready.")
        return
    if not args.media:
        raise SystemExit("请提供视频或音频路径。")
    media = Path(args.media)
    if not media.exists():
        raise SystemExit(f"File not found: {media}")

    t0 = time.time()
    print("Decoding audio ...", flush=True)
    samples = load_audio(media)
    duration = len(samples) / SAMPLE_RATE
    print(f"Audio: {format_time(duration)}", flush=True)

    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(models["sense-voice/model.int8.onnx"]),
        tokens=str(models["sense-voice/tokens.txt"]),
        num_threads=args.threads,
        use_itn=True,
        language="" if args.language == "auto" else args.language,
    )
    vad_cfg = sherpa_onnx.VadModelConfig()
    vad_cfg.silero_vad.model = str(models["silero_vad.onnx"])
    vad_cfg.silero_vad.threshold = 0.5
    vad_cfg.silero_vad.min_silence_duration = 0.3
    vad_cfg.silero_vad.min_speech_duration = 0.25
    try:
        vad_cfg.silero_vad.max_speech_duration = 12  # keep segments subtitle-sized (newer sherpa-onnx)
    except Exception:
        pass
    vad_cfg.sample_rate = SAMPLE_RATE
    window = vad_cfg.silero_vad.window_size
    vad = sherpa_onnx.VoiceActivityDetector(vad_cfg, buffer_size_in_seconds=120)

    segments: list[dict] = []
    next_report = 0.0

    def drain() -> None:
        nonlocal next_report
        while not vad.empty():
            seg = vad.front
            start = seg.start / SAMPLE_RATE
            end = start + len(seg.samples) / SAMPLE_RATE
            stream = recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, seg.samples)
            recognizer.decode_stream(stream)
            res = stream.result
            text = (res.text or "").strip()
            if text:
                tokens = list(getattr(res, "tokens", []) or [])
                stamps = list(getattr(res, "timestamps", []) or [])
                segments.extend(split_lines(text, tokens, stamps, start, end, args.max_chars))
            vad.pop()
            if start >= next_report:
                pct = start * 100 / duration if duration else 0
                print(f"  {format_time(start)} ({pct:.0f}%)  {text[:40]}", flush=True)
                next_report = start + 120

    for i in range(0, len(samples) - window + 1, window):  # VAD expects whole windows
        vad.accept_waveform(samples[i:i + window])
        drain()
    vad.flush()
    drain()

    if not segments:
        raise SystemExit("没有识别出任何语音。请确认文件有声音，或换 --language 再试。")

    base = Path(args.output) if args.output else media.parent / f"{media.stem}_转写"
    srt_path = base.parent / f"{base.name}.srt"
    write_srt(segments, srt_path)
    json_path = base.parent / f"{base.name}.segments.json"
    json_path.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote SRT: {srt_path}")
    print(f"Wrote segments JSON: {json_path}")
    if args.reading_copy:
        read_path = base.parent / f"{base.name}_阅读版.md"
        n = write_reading_copy(segments, read_path)
        print(f"Wrote reading copy: {read_path} ({n} paragraphs)")
    elapsed = time.time() - t0
    print(f"Done in {elapsed:.0f}s (audio {duration:.0f}s, speed x{duration / max(elapsed, 1):.0f}), "
          f"{len(segments)} lines")


if __name__ == "__main__":
    main()

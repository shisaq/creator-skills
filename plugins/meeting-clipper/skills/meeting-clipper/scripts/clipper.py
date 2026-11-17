#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["imageio-ffmpeg>=0.5"]
# ///
"""Meeting video clipper: environment check, transcript preparation, chapter validation, splitting.

Cross-platform (macOS / Windows / Linux). Run with `uv run clipper.py <command> ...`
so dependencies install automatically; plain `python clipper.py` also works when
ffmpeg is on PATH or imageio-ffmpeg is installed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

for _stream in (sys.stdout, sys.stderr):
    try:  # Windows consoles default to GBK/cp1252; keep Chinese output readable.
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

VALID_SCORES = {"A", "B", "C"}
CHAPTER_CORE_FIELDS = {"title", "start_time", "end_time", "summary", "type", "score"}
MANIFEST_BASE_FIELDS = [
    "index", "file", "filename", "source_video", "source_start_time", "source_end_time",
    "cut_start_time", "cut_end_time", "pad_start_seconds", "pad_end_seconds",
    "video_encoder", "clip_srt", "title", "type", "score", "summary",
]
TIMESTAMP_RE = re.compile(
    r"(?P<start>(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)"
    r"(?:\s*(?:-|–|—|~|至|到)\s*(?P<end>(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?))?"
)
SRT_RANGE_RE = re.compile(
    r"(?P<start>(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{1,3})"
)
# Hardware H.264 encoders to probe, in preference order, per platform.
HW_CANDIDATES = {
    "Darwin": ["h264_videotoolbox"],
    "Windows": ["h264_nvenc", "h264_qsv", "h264_amf"],
    "Linux": ["h264_nvenc", "h264_qsv", "h264_vaapi"],
}
ENCODER_ALIASES = {
    "videotoolbox": "h264_videotoolbox",
    "nvenc": "h264_nvenc",
    "qsv": "h264_qsv",
    "amf": "h264_amf",
    "cpu": "libx264",
    "x264": "libx264",
}


# --------------------------------------------------------------------------- ffmpeg

_FFMPEG: Optional[str] = None


def ffmpeg_exe() -> str:
    """Prefer ffmpeg on PATH (usually has more hardware encoders); fall back to imageio-ffmpeg's bundled binary."""
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    env = os.environ.get("MEETING_CLIPPER_FFMPEG")
    candidates = [env] if env else []
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    for cand in candidates:
        if cand and Path(cand).exists():
            _FFMPEG = cand
            return cand
    try:
        import imageio_ffmpeg  # type: ignore

        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        return _FFMPEG
    except Exception:
        raise SystemExit(
            "找不到 ffmpeg。推荐用 `uv run` 运行本脚本（会自动带上 ffmpeg）；"
            "或安装 ffmpeg（macOS: brew install ffmpeg；Windows: winget install Gyan.FFmpeg），"
            "或 pip install imageio-ffmpeg。"
        )


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def get_media_duration(path: Path) -> float:
    """Read duration from ffmpeg's banner (avoids needing ffprobe, which imageio-ffmpeg does not ship)."""
    result = run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], check=False)
    match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", result.stderr)
    if not match:
        raise SystemExit(f"无法读取视频时长：{path}\n{result.stderr[-500:]}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def encoder_works(encoder: str) -> bool:
    """An encoder can be listed but unusable (e.g. nvenc without an NVIDIA GPU), so do a tiny test encode."""
    cmd = [
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.2",
        "-frames:v", "3", "-c:v", encoder, "-pix_fmt", "yuv420p", "-f", "null", "-",
    ]
    try:
        return run(cmd, check=False).returncode == 0
    except OSError:
        return False


def pick_encoder(requested: str) -> str:
    requested = (requested or "auto").strip().lower()
    requested = ENCODER_ALIASES.get(requested, requested)
    if requested != "auto":
        if requested != "libx264" and not encoder_works(requested):
            print(f"WARN  编码器 {requested} 不可用，改用 CPU 编码 libx264")
            return "libx264"
        return requested
    for enc in HW_CANDIDATES.get(platform.system(), []):
        if encoder_works(enc):
            return enc
    return "libx264"


def encode_args(encoder: str, args: argparse.Namespace) -> list[str]:
    if encoder == "libx264":
        return ["-c:v", "libx264", "-crf", str(args.crf), "-preset", args.preset, "-pix_fmt", "yuv420p"]
    base = ["-c:v", encoder, "-b:v", args.video_bitrate, "-maxrate", args.video_bitrate,
            "-bufsize", args.video_bitrate]
    if encoder != "h264_vaapi":
        base += ["-pix_fmt", "yuv420p"]
    return base


# --------------------------------------------------------------------------- time & text helpers


def parse_time(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    parts = text.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError as exc:
        raise ValueError(f"Invalid time: {value}") from exc
    raise ValueError(f"Invalid time: {value}")


def format_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_srt_time(seconds: float) -> str:
    ms_total = int(round(max(0.0, float(seconds)) * 1000))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def sanitize_filename(value: str, fallback: str) -> str:
    value = value.strip() or fallback
    value = value.replace(" ", "_").replace("/", "_").replace("\\", "_")
    value = re.sub(r'[<>:"|?*\x00-\x1f]', "", value)
    value = re.sub(r"_+", "_", value).strip("._ ")
    return value[:80] or fallback


def read_text_any(path: Path) -> str:
    """Transcripts exported on Windows are often GBK; try the common encodings."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- transcripts


def parse_srt_or_vtt(text: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal current, lines
        if current is not None:
            content = " ".join(line.strip() for line in lines if line.strip())
            content = re.sub(r"<[^>]+>", "", content).strip()
            if content:
                current["text"] = content
                segments.append(current)
        current = None
        lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.upper().startswith("WEBVTT") or (line.isdigit() and current is None):
            flush()
            continue
        match = SRT_RANGE_RE.search(line)
        if match:
            flush()
            current = {"start": parse_time(match.group("start")), "end": parse_time(match.group("end")),
                       "speaker": "", "text": ""}
            continue
        if current is not None:
            lines.append(line)
    flush()
    return segments


def parse_plain_timestamps(text: str, default_duration: float) -> list[dict[str, Any]]:
    """Lines like `[00:12:08] 张三: ...`, `00:12:08 - 00:12:40 张三 ...` (Feishu/Tencent/Zoom text exports)."""
    segments: list[dict[str, Any]] = []
    pending_speaker = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = TIMESTAMP_RE.search(line)
        if not match or match.start() > 40:
            if segments:
                # Text continuing on the next line belongs to the previous timestamp.
                segments[-1]["text"] = (segments[-1]["text"] + " " + line).strip()
            continue
        start = parse_time(match.group("start"))
        end = parse_time(match.group("end")) if match.group("end") else None
        before = line[: match.start()].strip(" []()（）-–—\t")
        after = line[match.end():].strip(" []()（）-–—\t")
        speaker = before if 0 < len(before) <= 30 else pending_speaker
        content = after
        for sep in (":", "："):
            if sep in content:
                head, tail = content.split(sep, 1)
                if 0 < len(head.strip()) <= 30:
                    speaker, content = head.strip(), tail.strip()
                break
        segments.append({"start": start, "end": end, "speaker": speaker, "text": content})
    segments.sort(key=lambda s: s["start"])
    for i, seg in enumerate(segments):
        if seg["end"] is None:
            nxt = segments[i + 1]["start"] if i + 1 < len(segments) else seg["start"] + default_duration
            seg["end"] = max(seg["start"], nxt)
    return segments


def load_segments(path: Path, default_duration: float = 8.0) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"文件不存在：{path}")
    if path.suffix.lower() == ".json":
        data = json.loads(read_text_any(path))
        segments = data.get("segments", data) if isinstance(data, dict) else data
        return [dict(s) for s in segments]
    text = read_text_any(path)
    segments = parse_srt_or_vtt(text)
    if not segments:
        segments = parse_plain_timestamps(text, default_duration)
    return segments


def write_srt(segments: list[dict[str, Any]], output: Path) -> None:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        text = str(seg.get("text", "")).strip()
        if seg.get("speaker"):
            text = f"{seg['speaker']}: {text}"
        lines += [str(i), f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}", text, ""]
    output.write_text("\n".join(lines), encoding="utf-8")


def write_reading_copy(segments: list[dict[str, Any]], output: Path, block_seconds: float = 25.0) -> int:
    """A compact copy for the agent to read: short subtitle lines merged into ~25s paragraphs.

    Reading thousands of 2-second subtitle lines wastes context; paragraphs keep the meaning
    and a start time per paragraph. Precise cut points are refined later against the SRT.
    """
    blocks: list[tuple[float, str, str]] = []
    cur_start: Optional[float] = None
    cur_speaker = ""
    cur_text: list[str] = []
    for seg in segments:
        speaker = str(seg.get("speaker", "") or "")
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        new_block = (
            cur_start is None
            or seg["start"] - cur_start >= block_seconds
            or (speaker and speaker != cur_speaker)
        )
        if new_block:
            if cur_start is not None:
                blocks.append((cur_start, cur_speaker, "".join(cur_text) if _is_cjk("".join(cur_text)) else " ".join(cur_text)))
            cur_start, cur_speaker, cur_text = seg["start"], speaker, []
        cur_text.append(text)
    if cur_start is not None:
        blocks.append((cur_start, cur_speaker, "".join(cur_text) if _is_cjk("".join(cur_text)) else " ".join(cur_text)))

    with output.open("w", encoding="utf-8") as fh:
        fh.write("# 会议文字稿（阅读版，约每 25 秒一段；精确时间以 SRT 为准）\n\n")
        for start, speaker, text in blocks:
            who = f" {speaker}：" if speaker else " "
            fh.write(f"[{format_time(start)}]{who}{text}\n\n")
    return len(blocks)


def _is_cjk(text: str) -> bool:
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return cjk > len(text) * 0.3


def prepare_outputs(segments: list[dict[str, Any]], base: Path, overwrite_srt: bool = False) -> None:
    """Write <base>.srt, <base>.segments.json and <base>_阅读版.md.

    `base` is a path without extension; names are built by string concatenation because
    Path.with_suffix would treat any dot in a meeting title as an extension.
    """
    srt_path = base.parent / f"{base.name}.srt"
    if overwrite_srt or not srt_path.exists():
        write_srt(segments, srt_path)
        print(f"Wrote SRT: {srt_path}")
    json_path = base.parent / f"{base.name}.segments.json"
    json_path.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=1), encoding="utf-8")
    read_path = base.parent / f"{base.name}_阅读版.md"
    n = write_reading_copy(segments, read_path)
    print(f"Wrote segments JSON: {json_path}")
    print(f"Wrote reading copy: {read_path} ({n} paragraphs)")
    if segments:
        print(f"Transcript span: {format_time(segments[0]['start'])} -> {format_time(segments[-1]['end'])}, "
              f"{len(segments)} segments")


def cmd_prepare(args: argparse.Namespace) -> None:
    source = Path(args.transcript)
    segments = load_segments(source, args.default_duration)
    if not segments:
        raise SystemExit(
            "文字稿里没有找到时间戳。没有时间戳的纪要只能当内容参考，请改用 transcribe.py 从视频转写。"
        )
    segments.sort(key=lambda s: s["start"])
    prepare_outputs(segments, source.parent / source.stem)


# --------------------------------------------------------------------------- doctor


def cmd_doctor(args: argparse.Namespace) -> None:
    print(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python: {sys.version.split()[0]} at {sys.executable}")
    exe = ffmpeg_exe()
    source = "PATH" if shutil.which("ffmpeg") == exe else "bundled (imageio-ffmpeg)"
    print(f"ffmpeg: {exe} [{source}]")
    hw = [enc for enc in HW_CANDIDATES.get(platform.system(), []) if encoder_works(enc)]
    print(f"Hardware H.264 encoders usable: {', '.join(hw) if hw else 'none (will use CPU libx264)'}")
    print(f"Auto encoder choice: {pick_encoder('auto')}")
    model_dir = Path(os.environ.get("CREATOR_SKILLS_MODELS") or os.environ.get("MEETING_CLIPPER_MODELS")
                     or Path.home() / ".cache" / "creator-skills" / "models")
    sv = model_dir / "sense-voice" / "model.int8.onnx"
    vad = model_dir / "silero_vad.onnx"
    print(f"Transcription models dir: {model_dir}")
    print(f"  SenseVoice model: {'ready' if sv.exists() else 'not downloaded (first transcribe downloads ~240MB)'}")
    print(f"  VAD model: {'ready' if vad.exists() else 'not downloaded'}")
    try:
        import sherpa_onnx  # type: ignore  # noqa: F401

        print("sherpa-onnx: installed in this environment")
    except Exception:
        print("sherpa-onnx: not in this environment (transcribe.py installs it automatically via uv)")


# --------------------------------------------------------------------------- chapters


def load_chapters(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Chapters JSON not found: {path}")
    data = json.loads(read_text_any(path))
    chapters = data.get("chapters", []) if isinstance(data, dict) else data
    if not isinstance(chapters, list):
        raise SystemExit("Chapters JSON must contain a `chapters` array.")
    return chapters


def cmd_validate(args: argparse.Namespace) -> None:
    chapters = load_chapters(Path(args.chapters))
    duration: Optional[float] = None
    if args.video:
        duration = get_media_duration(Path(args.video))
        print(f"Video duration: {format_time(duration)}")

    errors: list[str] = []
    warnings: list[str] = []
    prev_end, prev_title = -1.0, ""
    for index, chapter in enumerate(chapters, 1):
        title = str(chapter.get("title", f"(chapter {index})"))
        prefix = f"[{index}] {title}"
        if "start_time" not in chapter or "end_time" not in chapter:
            errors.append(f"{prefix}: missing start_time or end_time")
            continue
        try:
            start, end = parse_time(chapter["start_time"]), parse_time(chapter["end_time"])
        except ValueError as exc:
            errors.append(f"{prefix}: {exc}")
            continue
        if end <= start:
            errors.append(f"{prefix}: end_time must be after start_time ({format_time(start)} -> {format_time(end)})")
            continue
        if duration is not None and end > duration + 0.5:
            errors.append(f"{prefix}: end_time {format_time(end)} exceeds video duration {format_time(duration)}")
        if end - start < 10:
            warnings.append(f"{prefix}: very short clip ({end - start:.0f}s)")
        if start < prev_end:
            warnings.append(f"{prefix}: overlaps previous clip '{prev_title}'")
        score = str(chapter.get("score", "") or "").strip().upper()
        if score and score not in VALID_SCORES:
            errors.append(f"{prefix}: invalid score {chapter['score']!r}; expected A / B / C")
        prev_end, prev_title = end, title

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"\nValidated {len(chapters)} chapters: {len(errors)} error(s), {len(warnings)} warning(s).")
    if errors:
        raise SystemExit(1)


# --------------------------------------------------------------------------- split


def write_clip_srt(segments: list[dict[str, Any]], output: Path, cut_start: float, cut_end: float) -> int:
    rows = []
    for seg in segments:
        start, end = float(seg["start"]), float(seg["end"])
        if end <= cut_start or start >= cut_end:
            continue
        s, e = max(start, cut_start) - cut_start, min(end, cut_end) - cut_start
        text = str(seg.get("text", "")).strip()
        if e > s and text:
            rows.append({"start": s, "end": e, "text": text, "speaker": seg.get("speaker", "")})
    write_srt(rows, output)
    return len(rows)


def build_cut_cmd(video: Path, output: Path, cut_start: float, duration: float,
                  venc: list[str], args: argparse.Namespace) -> list[str]:
    # -ss before -i seeks on the input: fast on long recordings, and frame-accurate when re-encoding.
    head = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{cut_start:.3f}", "-i", str(video), "-t", f"{duration:.3f}"]
    if args.fast_copy:
        return head + ["-c", "copy", "-avoid_negative_ts", "make_zero", str(output)]
    return head + venc + ["-c:a", "aac", "-b:a", args.audio_bitrate,
                          "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(output)]


def cmd_split(args: argparse.Namespace) -> None:
    video = Path(args.video)
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")
    chapters = load_chapters(Path(args.chapters))
    if args.scores:
        wanted = {s.strip().upper() for s in args.scores.split(",") if s.strip()}
        chapters = [c for c in chapters if str(c.get("score", "")).strip().upper() in wanted]
        print(f"Filtered to scores {sorted(wanted)}: {len(chapters)} chapters")
    output_dir = Path(args.output_dir) if args.output_dir else video.with_name(f"{video.stem}_切片")
    output_dir.mkdir(parents=True, exist_ok=True)
    video_duration = get_media_duration(video)

    encoder = "copy" if args.fast_copy else pick_encoder(args.encoder)
    venc = [] if args.fast_copy else encode_args(encoder, args)
    print(f"Encoder: {encoder}")

    srt_segments: list[dict[str, Any]] = []
    if args.transcript:
        srt_segments = load_segments(Path(args.transcript))
        print(f"Per-clip SRT: on ({len(srt_segments)} transcript segments)")

    manifest: list[dict[str, Any]] = []
    total = len(chapters)
    for index, chapter in enumerate(chapters, 1):
        title = sanitize_filename(str(chapter.get("title", "")), f"clip_{index:02d}")
        source_start, source_end = parse_time(chapter["start_time"]), parse_time(chapter["end_time"])
        if source_end <= source_start:
            print(f"Skipping {title}: end_time must be after start_time")
            continue
        cut_start = max(0.0, source_start - args.pad_start)
        cut_end = min(video_duration, source_end + args.pad_end)
        score = str(chapter.get("score", "") or "").strip().upper()
        score_prefix = f"{score}_" if score in VALID_SCORES else ""
        numbered = title if re.match(r"^\d{2}_", title) else f"{index:02d}_{title}"
        output = output_dir / f"{score_prefix}{numbered}.mp4"
        print(f"[{index}/{total}] {format_time(cut_start)} -> {format_time(cut_end)} {output.name}", flush=True)

        used = encoder
        result = run(build_cut_cmd(video, output, cut_start, cut_end - cut_start, venc, args), check=False)
        if result.returncode != 0 and not args.fast_copy and encoder != "libx264":
            print(f"WARN  {encoder} failed on this clip, retrying with libx264")
            used = "libx264"
            result = run(build_cut_cmd(video, output, cut_start, cut_end - cut_start,
                                       encode_args("libx264", args), args), check=False)
        if result.returncode != 0:
            print(f"ERROR {output.name}: {result.stderr[-800:]}")
            continue

        clip_srt = ""
        if srt_segments:
            srt_out = output.with_suffix(".srt")
            write_clip_srt(srt_segments, srt_out, cut_start, cut_end)
            clip_srt = srt_out.name
        row: dict[str, Any] = {
            "index": index, "file": str(output), "filename": output.name, "source_video": str(video),
            "source_start_time": format_time(source_start), "source_end_time": format_time(source_end),
            "cut_start_time": format_time(cut_start), "cut_end_time": format_time(cut_end),
            "pad_start_seconds": args.pad_start, "pad_end_seconds": args.pad_end,
            "video_encoder": used, "clip_srt": clip_srt, "title": title,
            "type": chapter.get("type", ""), "score": score, "summary": chapter.get("summary", ""),
        }
        for key, value in chapter.items():
            if key not in CHAPTER_CORE_FIELDS and key not in row:
                row[key] = value
        manifest.append(row)

    if manifest:
        (output_dir / "clip_manifest.json").write_text(
            json.dumps({"clips": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
        fieldnames = MANIFEST_BASE_FIELDS + [k for r in manifest for k in r if k not in MANIFEST_BASE_FIELDS]
        fieldnames = list(dict.fromkeys(fieldnames))
        # utf-8-sig so Excel on Windows opens the Chinese CSV correctly.
        with (output_dir / "clip_manifest.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(manifest)
        print(f"Wrote manifest: {output_dir / 'clip_manifest.csv'} (+ .json)")
    print(f"Finished: {len(manifest)}/{total} clips written to {output_dir}")


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Clip meeting recordings into standalone segments.")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="Check ffmpeg, encoders and transcription models.")
    d.set_defaults(func=cmd_doctor)

    pr = sub.add_parser("prepare-transcript", help="Parse a timestamped transcript (srt/vtt/txt/md/json).")
    pr.add_argument("transcript")
    pr.add_argument("--default-duration", type=float, default=8.0,
                    help="Seconds assumed for lines that only have a start time.")
    pr.set_defaults(func=cmd_prepare)

    v = sub.add_parser("validate", help="Validate a chapters JSON before splitting.")
    v.add_argument("--chapters", required=True)
    v.add_argument("--video")
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("split", help="Cut the video by chapters JSON.")
    s.add_argument("video")
    s.add_argument("--chapters", required=True)
    s.add_argument("--output-dir")
    s.add_argument("--transcript", help="Full-length SRT/VTT/segments.json; writes a matching .srt per clip.")
    s.add_argument("--scores", help="Only cut these scores, e.g. A,B")
    s.add_argument("--pad-start", type=float, default=2.0)
    s.add_argument("--pad-end", type=float, default=5.0)
    s.add_argument("--encoder", "--hardware-encoder", dest="encoder", default="auto",
                   help="auto (default) | cpu | videotoolbox | nvenc | qsv | amf | any ffmpeg encoder name")
    s.add_argument("--video-bitrate", default="8000k", help="Bitrate for hardware encoders.")
    s.add_argument("--crf", type=int, default=20, help="Quality for CPU libx264 (lower = better/larger).")
    s.add_argument("--preset", default="veryfast", help="libx264 preset.")
    s.add_argument("--audio-bitrate", default="160k")
    s.add_argument("--fast-copy", action="store_true", help="Stream copy: very fast, cuts snap to keyframes.")
    s.set_defaults(func=cmd_split)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

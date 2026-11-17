#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""srt_tools.py — the deterministic half of subtitle polishing and translation.

The model only ever writes *text* (one line per cue number); this script owns the
timeline, so timecodes, cue order and cue count can never drift.

extract   <sub>   Parse SRT/VTT/ASS, print `n|text` lines, save timecodes to <sub>.cues.json
apply     <sub>   Polish: read <sub>.edits.txt (`n|new text[|type]`, changed cues only),
                  write <stem>_润色.srt and <stem>_润色明细.md (diff table)
build     <sub>   Translate: read <sub>.translations.txt (`n|text`, every cue),
                  write <stem>_<lang>.srt and check alignment / leftover source script / reading speed
bilingual <ass>   Bilingual ASS (source on top, translation below), style derived from Default
atpj      <ass>   Inject the translation track into an Arctime project (<stem>.atpj -> <stem>-双语.atpj)

No third-party dependencies: `uv run srt_tools.py ...` or plain `python3 srt_tools.py ...`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import uuid
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")
KANA_HANGUL_RE = re.compile(r"[぀-ヿ가-힯]")
TIME_RE = re.compile(r"(\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{1,3}")
# Comfortable reading speed. Latin scripts count characters incl. spaces; CJK counts characters.
DEFAULT_CPS = {"latin": 20, "cjk": 9}
CJK_TARGETS = {"zh", "zh-hans", "zh-hant", "ja", "ko", "yue"}
EN_GROUP = 2  # Arctime bilingual convention: source = group 1 (atg1), translation = group 2 (atg2)


# --------------------------------------------------------------------------- parsing


def norm_time(t: str) -> str:
    """Any of `1:02.5`, `00:01:02.500`, `00:01:02,5` -> `00:01:02,500`."""
    t = t.strip().replace(".", ",")
    hms, _, frac = t.partition(",")
    parts = hms.split(":")
    if len(parts) == 2:
        parts = ["0"] + parts
    h, m, s = (int(p) for p in parts)
    ms = int((frac + "000")[:3]) if frac else 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_to_ms(t: str) -> int:
    h, m, rest = norm_time(t).split(":")
    s, ms = rest.split(",")
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def ass_time_to_srt(t: str) -> str:
    h, m, s = t.strip().split(":")
    sec, cs = s.split(".")
    return f"{int(h):02d}:{m}:{sec},{int(cs) * 10:03d}"


def parse_srt(text: str):
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip().lstrip("﻿")):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        left, right = lines[idx].split("-->", 1)
        m1, m2 = TIME_RE.search(left), TIME_RE.search(right)
        if not (m1 and m2):
            continue
        body = " ".join(lines[idx + 1:]).strip()
        body = re.sub(r"<[^>]+>", "", body)  # VTT/HTML styling tags
        if body:
            cues.append({"start": norm_time(m1.group(0)), "end": norm_time(m2.group(0)), "text": body})
    return cues


def parse_ass(text: str):
    cues = []
    fmt = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Format:") and "Start" in line and "Text" in line:
            fmt = [f.strip() for f in line[len("Format:"):].split(",")]
        elif line.startswith("Dialogue:") and fmt:
            parts = line[len("Dialogue:"):].split(",", len(fmt) - 1)
            if len(parts) < len(fmt):
                continue
            d = dict(zip(fmt, [p.strip() for p in parts]))
            body = re.sub(r"\{[^}]*\}", "", d.get("Text", ""))
            body = body.replace("\\N", " ").replace("\\n", " ").strip()
            if body:
                cues.append({"start": ass_time_to_srt(d["Start"]), "end": ass_time_to_srt(d["End"]), "text": body})
    cues.sort(key=lambda c: c["start"])
    return cues


def read_text_any(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_cues(path: Path):
    if not path.exists():
        sys.exit(f"错误：找不到 {path}")
    text = read_text_any(path)
    cues = parse_ass(text) if path.suffix.lower() == ".ass" else parse_srt(text)
    if not cues:
        sys.exit(f"错误：{path} 中没有解析到任何字幕条目")
    return cues


def sidecar(path: Path, ext: str) -> Path:
    return path.with_name(path.name + ext)


def out_name(src: Path, suffix: str) -> Path:
    """<stem><suffix>.srt next to the source; stem keeps any dots in the title."""
    return src.with_name(src.stem + suffix)


def write_srt(cues, texts, output: Path) -> None:
    chunks = [f"{i}\n{c['start']} --> {c['end']}\n{texts[i]}\n" for i, c in enumerate(cues, 1)]
    output.write_text("\n".join(chunks), encoding="utf-8")


def load_numbered(path: Path, n_cues: int, require_all: bool, with_type: bool = False):
    """Parse `n|text` lines (or `n|text|type` when with_type). Returns {n: (text, type)}."""
    if not path.exists():
        sys.exit(f"错误：找不到 {path}")
    rows = {}
    for raw in read_text_any(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\d+)\s*[|｜]\s*(.*)$", line)
        if not m:
            sys.exit(f"错误：无法解析这一行（需要 '序号|文本'）：{line[:60]}")
        body = m.group(2)
        kind = ""
        if with_type and "|" in body:
            body, _, kind = body.rpartition("|")
        rows[int(m.group(1))] = (body.strip(), kind.strip())
    extra = sorted(i for i in rows if i < 1 or i > n_cues)
    if extra:
        sys.exit(f"错误：序号超出范围 {extra[:20]}（原文共 {n_cues} 条）")
    if require_all:
        missing = [i for i in range(1, n_cues + 1) if not rows.get(i, ("", ""))[0]]
        if missing:
            sys.exit(f"错误：缺少 {len(missing)} 条译文，序号：{missing[:20]}（原文共 {n_cues} 条）")
    return rows


def load_saved_cues(src: Path):
    cues_json = sidecar(src, ".cues.json")
    if not cues_json.exists():
        sys.exit(f"错误：找不到 {cues_json.name}，请先运行 extract")
    return json.loads(cues_json.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- commands


def cmd_extract(args):
    src = Path(args.file).expanduser().resolve()
    cues = load_cues(src)
    sidecar(src, ".cues.json").write_text(json.dumps(cues, ensure_ascii=False, indent=1), encoding="utf-8")
    for i, c in enumerate(cues, 1):
        print(f"{i}|{c['text']}")
    total = srt_to_ms(cues[-1]["end"]) / 1000
    print(f"\n--- 共 {len(cues)} 条，时长约 {total / 60:.1f} 分钟；时间码已存入 {src.name}.cues.json ---",
          file=sys.stderr)


def cmd_apply(args):
    src = Path(args.file).expanduser().resolve()
    cues = load_saved_cues(src)
    edits = load_numbered(sidecar(src, ".edits.txt"), len(cues), require_all=False, with_type=True)
    texts = {i: c["text"] for i, c in enumerate(cues, 1)}
    changes = []
    for i, (new, kind) in sorted(edits.items()):
        if not new:
            sys.exit(f"错误：#{i} 的修改为空。要删字请写出删后的完整文本；整条删除请保留原文并在汇报里说明。")
        if new != texts[i]:
            changes.append((i, texts[i], new, kind))
            texts[i] = new
    out = out_name(src, "_润色.srt")
    write_srt(cues, texts, out)

    report = out_name(src, "_润色明细.md")
    lines = [f"# 润色明细：{src.name}", "", f"共 {len(cues)} 条字幕，修改 {len(changes)} 条。", "",
             "| 序号 | 时间 | 原文 | 修正后 | 类型 |", "|---|---|---|---|---|"]
    for i, old, new, kind in changes:
        lines.append(f"| {i} | {cues[i - 1]['start'][:8]} | {old} | {new} | {kind} |")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成: {out}")
    print(f"修改明细: {report}（{len(changes)} 处）")
    print("时间轴、序号、条数与原文件完全一致")


def cmd_build(args):
    src = Path(args.file).expanduser().resolve()
    cues = load_saved_cues(src)
    rows = load_numbered(sidecar(src, ".translations.txt"), len(cues), require_all=True)
    texts = {i: rows[i][0] for i in rows}
    lang = args.lang.lower()
    cjk_target = lang in CJK_TARGETS
    max_cps = args.max_cps or DEFAULT_CPS["cjk" if cjk_target else "latin"]
    out = out_name(src, f"_{lang}.srt")
    write_srt(cues, texts, out)

    warnings = []
    for i, c in enumerate(cues, 1):
        t = texts[i]
        if not cjk_target and (CJK_RE.search(t) or KANA_HANGUL_RE.search(t)):
            warnings.append(f"#{i} 残留源语言字符: {t}")
        dur = (srt_to_ms(c["end"]) - srt_to_ms(c["start"])) / 1000
        if dur > 0 and len(t) / dur > max_cps:
            warnings.append(f"#{i} 阅读速度 {len(t) / dur:.0f} 字/秒 (>{max_cps})，时长 {dur:.1f}s: {t}")
    print(f"已生成: {out}")
    print(f"共 {len(cues)} 条，时间轴与原文件逐条一致")
    if warnings:
        print(f"\n⚠️ {len(warnings)} 条警告（压缩这些译文后重新 build）:")
        for w in warnings:
            print(f"  {w}")
        sys.exit(2)
    print("校验通过：无残留源语言字符，阅读速度均达标")


def default_l2_font(arg: str | None) -> str:
    return arg or os.environ.get("SUBTITLE_L2_FONT") or "Arial"


def build_l2_style(ass_lines, l2_font, size_arg, marginv_arg):
    """Derive the translation style Default-L2 from Default: same colours/outline/border,
    only font, size and MarginV change (mirrors adding a second track by hand in Arctime)."""
    style_fmt = default_vals = None
    in_styles = False
    for line in ass_lines:
        s = line.strip()
        if s.startswith("["):
            in_styles = s.lower().startswith("[v4")
        elif in_styles and s.startswith("Format:"):
            style_fmt = [f.strip() for f in s[len("Format:"):].split(",")]
        elif in_styles and s.startswith("Style:") and style_fmt:
            vals = [v.strip() for v in s[len("Style:"):].split(",")]
            if vals[style_fmt.index("Name")] == "Default":
                default_vals = vals
    if not (style_fmt and default_vals):
        sys.exit("错误：ASS 中找不到 Default 样式")
    fi = style_fmt.index
    src_size = float(default_vals[fi("Fontsize")])
    src_marginv = float(default_vals[fi("MarginV")])
    size = size_arg or round(src_size * 40 / 77)  # translation ≈ half the source size
    marginv = marginv_arg or round(src_marginv - size - 1)  # sit right under the source line
    vals = list(default_vals)
    vals[fi("Name")] = "Default-L2"
    vals[fi("Fontname")] = l2_font
    vals[fi("Fontsize")] = str(size)
    vals[fi("MarginV")] = str(marginv)
    return "Style: " + ",".join(vals), size, marginv


def translated_rows(src: Path, n: int):
    rows = load_numbered(sidecar(src, ".translations.txt"), n, require_all=True)
    return {i: rows[i][0] for i in rows}


def cmd_bilingual(args):
    src = Path(args.file).expanduser().resolve()
    if src.suffix.lower() != ".ass":
        sys.exit("错误：bilingual 只接受 .ass 文件")
    lines = read_text_any(src).splitlines()
    l2_font = default_l2_font(args.l2_font)

    default_line_idx = l2_line_idx = None
    style_fmt = event_fmt = None
    in_styles = in_events = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("["):
            in_styles = s.lower().startswith("[v4")
            in_events = s.lower() == "[events]"
        elif in_styles and s.startswith("Format:"):
            style_fmt = [f.strip() for f in s[len("Format:"):].split(",")]
        elif in_styles and s.startswith("Style:") and style_fmt:
            name = [v.strip() for v in s[len("Style:"):].split(",")][style_fmt.index("Name")]
            if name == "Default":
                default_line_idx = i
            elif name == "Default-L2":
                l2_line_idx = i
        elif in_events and s.startswith("Format:"):
            event_fmt = [f.strip() for f in s[len("Format:"):].split(",")]
    if default_line_idx is None or not event_fmt:
        sys.exit("错误：ASS 中找不到 Default 样式或 Events Format 行")
    l2_style, size, marginv = build_l2_style(lines, l2_font, args.l2_size, args.l2_marginv)

    dlg = {}
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("Dialogue:"):
            continue
        parts = s[len("Dialogue:"):].split(",", len(event_fmt) - 1)
        if len(parts) < len(event_fmt):
            continue
        d = dict(zip(event_fmt, [p.strip() for p in parts]))
        body = re.sub(r"\{[^}]*\}", "", d.get("Text", "")).replace("\\N", " ").replace("\\n", " ").strip()
        if body:
            dlg[i] = d
    order = sorted(dlg, key=lambda i: (ass_time_to_srt(dlg[i]["Start"]), i))  # same order as extract
    cue_no = {line_idx: n for n, line_idx in enumerate(order, 1)}
    texts = translated_rows(src, len(order))

    out_lines = []
    for i, line in enumerate(lines):
        if i == l2_line_idx:
            out_lines.append(l2_style)
            continue
        m = re.match(r"^(\s*;\s*ArctimeTrackCount:\s*)(\d+)\s*$", line)
        if m:
            out_lines.append(f"{m.group(1)}{int(m.group(2)) + 1}")
            continue
        if i in cue_no:
            d = dlg[i]
            layer = int(d.get("Layer", "0") or 0) + 1
            out_lines.append(f"Dialogue: {layer},{d['Start']},{d['End']},Default-L2,atg2,0,0,0,,{texts[cue_no[i]]}")
        out_lines.append(line)
        if i == default_line_idx and l2_line_idx is None:
            out_lines.append(l2_style)

    out = src.with_name(src.stem + "-双语.ass")
    out.write_bytes("\r\n".join(out_lines).encode("utf-8-sig"))  # Arctime-style: BOM + CRLF
    print(f"已生成: {out}")
    print(f"共插入 {len(order)} 条译文行（Default-L2 / atg2，时间码与原文逐条一致）")
    print(f"译文样式: 字体 {l2_font}，字号 {size}，MarginV {marginv}（其余继承 Default）")


def cmd_atpj(args):
    src = Path(args.file).expanduser().resolve()
    if src.suffix.lower() != ".ass":
        sys.exit("错误：atpj 只接受 .ass 文件（同目录须有同名 .atpj）")
    atpj_in = src.with_name(src.stem + ".atpj")
    if not atpj_in.exists():
        sys.exit(f"错误：找不到 Arctime 工程文件 {atpj_in.name}")
    cues = load_saved_cues(src)
    texts = translated_rows(src, len(cues))
    l2_font = default_l2_font(args.l2_font)
    l2_style, size, marginv = build_l2_style(read_text_any(src).splitlines(), l2_font, args.l2_size, args.l2_marginv)

    raw = atpj_in.read_text(encoding="utf-8-sig")
    proj = json.loads(raw)
    ascii_only = raw.isascii()  # Arctime writes ASCII with %XX-escaped text; keep it that way
    blocks = proj.get("BLOCKS")
    if not isinstance(blocks, list):
        sys.exit("错误：atpj 中没有 BLOCKS 列表，可能不是 Arctime 工程文件")
    if any(b.get("group") == EN_GROUP for b in blocks):
        sys.exit(f"错误：组 {EN_GROUP} 已被占用（约定用于译文轨），疑似已是双语工程，已终止")

    # Pair each cue with its source block: text must match exactly; time within 50ms
    # (.ass is centisecond precision, .atpj keeps milliseconds). Greedy in order, so
    # repeated lines each get their own block.
    used, l2_for, unmatched = set(), {}, []
    for n, c in enumerate(cues, 1):
        cstart = srt_to_ms(c["start"])
        best, best_diff = None, None
        for idx, b in enumerate(blocks):
            if idx in used or urllib.parse.unquote_plus(b.get("text", "")) != c["text"]:
                continue
            diff = abs((b.get("time_start") or 0) - cstart)
            if diff <= 50 and (best_diff is None or diff < best_diff):
                best, best_diff = idx, diff
        if best is None:
            unmatched.append(n)
            continue
        used.add(best)
        b = blocks[best]
        fmt = dict(b.get("format", {}))
        fmt["V4S"], fmt["CS"] = "Default-L2", False
        l2_for[id(b)] = {
            "name": str(uuid.uuid4()), "time_start": b["time_start"], "time_end": b["time_end"],
            "layer": 1, "text": urllib.parse.quote_plus(texts[n]), "group": EN_GROUP,
            "ismother": False, "ischild": False, "ishiden": False, "format": fmt,
        }
    if unmatched:
        sys.exit(f"错误：这些序号在 .atpj 里找不到文本和时间都吻合的块（.ass 与 .atpj 是否同源？）：{unmatched}")

    # Arctime's layer is a timeline track row. Give the translation its own top row and push
    # every existing block down one, otherwise both tracks overlap on the same row.
    for b in blocks:
        b["layer"] = int(b.get("layer", 1) or 1) + 1
    new_blocks = []
    for b in blocks:
        if id(b) in l2_for:
            new_blocks.append(l2_for[id(b)])
        new_blocks.append(b)
    proj["BLOCKS"] = new_blocks

    gs = proj.setdefault("GROUPSETTINGS", [])
    g2 = next((g for g in gs if g.get("index") == EN_GROUP), None)
    if g2 is None:
        gs.append({"index": EN_GROUP, "visible": True, "main_style": "Default-L2"})
    else:
        g2["visible"], g2["main_style"] = True, "Default-L2"
    styles = proj.setdefault("ASSSTYLES", [])
    quoted = urllib.parse.quote_plus(l2_style)
    hit = next((s for s in styles if isinstance(s, dict)
                and urllib.parse.unquote_plus(s.get("ass_string", "")).startswith("Style: Default-L2,")), None)
    if hit is None:
        styles.append({"ass_string": quoted})
    else:
        hit["ass_string"] = quoted
    max_layer = max([b["layer"] for b in new_blocks] + [1])
    for k in ("track_max", "track_max_v2"):
        if isinstance(proj.get(k), int):
            proj[k] = max(proj[k] + 1, max_layer + 1)

    out = src.with_name(src.stem + "-双语.atpj")
    out.write_text(json.dumps(proj, ensure_ascii=ascii_only, separators=(",", ":")), encoding="utf-8")
    print(f"已生成: {out}")
    print(f"共注入 {len(l2_for)} 条译文块（group {EN_GROUP} / Default-L2 / 顶层轨道，原有轨道顺次下移）")
    print(f"译文样式: 字体 {l2_font}，字号 {size}，MarginV {marginv}（其余继承 Default）")
    print("→ 用 Arctime 打开这个 -双语.atpj 直接出片；不要再导入 -双语.ass（会丢分组与样式）")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("extract", help="Parse SRT/VTT/ASS into numbered text + cues.json")
    s.add_argument("file")
    s.set_defaults(func=cmd_extract)
    s = sub.add_parser("apply", help="Polish: apply <file>.edits.txt")
    s.add_argument("file")
    s.set_defaults(func=cmd_apply)
    s = sub.add_parser("build", help="Translate: build <stem>_<lang>.srt from <file>.translations.txt")
    s.add_argument("file")
    s.add_argument("--lang", default="en", help="Target language code used in the filename and checks (en, ja, zh...)")
    s.add_argument("--max-cps", type=int, help="Reading-speed limit (default 20 Latin / 9 CJK chars per second)")
    s.set_defaults(func=cmd_build)
    for name, fn, helptext in (("bilingual", cmd_bilingual, "Bilingual ASS for burning in / uploading"),
                               ("atpj", cmd_atpj, "Inject translation track into an Arctime .atpj")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("file")
        s.add_argument("--l2-font", "--en-font", dest="l2_font",
                       help="Translation font (default $SUBTITLE_L2_FONT or Arial)")
        s.add_argument("--l2-size", "--en-size", dest="l2_size", type=int, help="Font size (default source×40/77)")
        s.add_argument("--l2-marginv", "--en-marginv", dest="l2_marginv", type=int,
                       help="MarginV (default: right under the source line)")
        s.set_defaults(func=fn)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

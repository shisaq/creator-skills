#!/usr/bin/env python3
"""Caption groups for the packaged video, timed to the character.

  python3 captions.py draft <cut>.words.json [--max 12] [--terms 马斯克,黄仁勋] > phrases.txt
      One caption group per line, broken at punctuation and pauses. Fix recognition errors and
      wording in this file (one group per line; text only, no times).

  python3 captions.py align <cut>.words.json phrases.txt --out captions.json [--srt captions.srt]
      Matches the corrected lines back onto the transcript (fuzzy, so corrections are fine) and
      writes [{"text", "start", "end"}]. Lines that match poorly are reported.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

PUN = re.compile(r"[\s，。！？；、,.!?;：:“”\"'（）()…—-]")


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))["tokens"]


FILLERS = {"嗯", "呃", "啊", "额", "唔"}


def draft(tokens, max_chars, terms=()):
    """Phrases at punctuation/pauses; over-long ones split at their biggest inner pause, never inside a term."""
    toks = [t for t in tokens if t["t"] not in FILLERS]
    phrases, cur = [], []
    for t in toks:
        cur.append(t)
        if t.get("p") or t.get("gap", 0) >= 0.2:
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)

    def split(ph):
        n = sum(len(t["t"]) for t in ph)
        if n <= max_chars or len(ph) < 2:
            return [ph]
        best, score = None, -1.0
        acc = 0
        text = "".join(t["t"] for t in ph)
        inside = set()
        for term in terms:
            k = text.find(term)
            while k >= 0:
                inside.update(range(k + 1, k + len(term)))
                k = text.find(term, k + 1)
        for i, t in enumerate(ph[:-1]):
            acc += len(t["t"])
            if acc < 3 or n - acc < 3 or acc in inside:
                continue
            s = t.get("gap", 0) + (t.get("e", 0) and ph[i + 1]["s"] - t["e"]) - abs(acc - n / 2) * 0.01
            if s > score:
                best, score = i, s
        if best is None:
            best = len(ph) // 2 - 1
        return split(ph[:best + 1]) + split(ph[best + 1:])

    out = []
    for ph in phrases:
        for part in split(ph):
            text = "".join(t["t"] for t in part)
            if out and len(text) <= 2 and len(out[-1]) + len(text) <= max_chars:
                out[-1] += text
            else:
                out.append(text)
    return out


def chars(tokens):
    cs, ts = [], []
    for t in tokens:
        txt = PUN.sub("", t["t"])
        n = len(txt)
        for i, c in enumerate(txt):
            cs.append(c)
            ts.append((t["s"] + (t["e"] - t["s"]) * i / n, t["s"] + (t["e"] - t["s"]) * (i + 1) / n))
    return "".join(cs), ts


def align(tokens, phrases):
    src, times = chars(tokens)
    ph = [PUN.sub("", p) for p in phrases]
    tgt = "".join(ph)
    sm = difflib.SequenceMatcher(None, tgt, src, autojunk=False)
    m = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            m[blk.a + k] = blk.b + k
    out, pos, weak = [], 0, []
    for raw, p in zip(phrases, ph):
        idx = [m[i] for i in range(pos, pos + len(p)) if i in m]
        if idx:
            st, en = times[idx[0]][0], times[idx[-1]][1]
        else:
            st = out[-1]["end"] if out else 0.0
            en = st + 0.3 * len(p)
        if len(p) and len(idx) / len(p) < 0.6:
            weak.append(raw)
        out.append({"text": raw.strip(), "start": round(st, 2), "end": round(en, 2), "_ok": len(idx) / max(1, len(p)) >= 0.6})
        pos += len(p)
    # a poorly matched line (e.g. digits vs. spoken numerals) takes the gap between its neighbours
    for i, c in enumerate(out):
        if not c["_ok"]:
            prev_end = out[i - 1]["end"] if i else c["start"]
            nxt = next((o["start"] for o in out[i + 1:] if o["_ok"]), c["end"])
            if nxt > prev_end:
                c["start"], c["end"] = round(prev_end + 0.02, 2), round(nxt - 0.02, 2)
    for c in out:
        c.pop("_ok")
    return out, weak


def srt(caps):
    def t(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    rows = []
    for i, c in enumerate(caps):
        en = min(c["end"] + 0.25, caps[i + 1]["start"] - 0.02) if i + 1 < len(caps) else c["end"]
        rows.append(f"{i + 1}\n{t(c['start'])} --> {t(max(en, c['start'] + 0.5))}\n{c['text']}\n")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("words")
    d.add_argument("--max", type=int, default=12)
    d.add_argument("--terms", default="", help="Comma-separated names that must not be split across lines.")
    a_ = sub.add_parser("align")
    a_.add_argument("words")
    a_.add_argument("phrases")
    a_.add_argument("--out", required=True)
    a_.add_argument("--srt")
    a = ap.parse_args()
    tokens = load(a.words)
    if a.cmd == "draft":
        sys.stdout.write("\n".join(draft(tokens, a.max, [x for x in a.terms.split(",") if x])) + "\n")
        return
    phrases = [l.strip() for l in Path(a.phrases).read_text(encoding="utf-8").splitlines() if l.strip()]
    caps, weak = align(tokens, phrases)
    Path(a.out).write_text(json.dumps(caps, ensure_ascii=False, indent=0), encoding="utf-8")
    if a.srt:
        Path(a.srt).write_text(srt(caps), encoding="utf-8")
    print(f"{len(caps)} captions → {a.out}")
    if weak:
        print("Matched poorly, timed from the neighbouring lines (check in the preview):")
        for w in weak:
            print("  -", w)


if __name__ == "__main__":
    main()

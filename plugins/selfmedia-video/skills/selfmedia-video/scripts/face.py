#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["opencv-python-headless>=4.8,<5", "numpy"]  # 5.x dropped the Haar CascadeClassifier
# ///
"""Track the speaker's face every 0.2 s.

Two things in packaging depend on where the face is, and a fixed guess gets both wrong:
  - captions go below the chin, never over the mouth;
  - the picture-in-picture window follows the face instead of a fixed crop.

    uv run face.py <video> [--step 0.2] [--out face.json]

Writes {"width", "height", "step", "samples": [[t, x, y, w, h], ...]} in source pixels.
A sample with no face repeats the previous one (null at the very start until a face is found).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    import cv2

    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--step", type=float, default=0.2)
    ap.add_argument("--out")
    a = ap.parse_args()
    video = Path(a.video).expanduser().resolve()
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    k = 2  # detect on a half-size frame
    step = max(1, int(round(fps * a.step)))
    out, last, found = [], None, 0
    for i in range(0, n, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(f, (W // k, H // k)), cv2.COLOR_BGR2GRAY)
        fs = casc.detectMultiScale(g, 1.1, 5, minSize=(W // k // 8, W // k // 8))
        if len(fs):
            x, y, w, h = max(fs, key=lambda r: r[2] * r[3])
            last = [int(x) * k, int(y) * k, int(w) * k, int(h) * k]
            found += 1
        out.append([round(i / fps, 2)] + (last if last else [None] * 4))
    # back-fill the start if the first frames had no face
    first = next((s for s in out if s[1] is not None), None)
    for s in out:
        if s[1] is None and first:
            s[1:] = first[1:]
    dst = Path(a.out) if a.out else video.with_suffix(".face.json")
    dst.write_text(json.dumps({"width": W, "height": H, "step": a.step, "samples": out}), encoding="utf-8")
    ok = [s for s in out if s[1] is not None]
    if ok:
        print(f"{len(out)} samples, face found in {found}; face centre x {min(s[1]+s[3]/2 for s in ok):.0f}–"
              f"{max(s[1]+s[3]/2 for s in ok):.0f}, chin (box bottom) up to {max(s[2]+s[4] for s in ok):.0f}px")
    else:
        print("No face found: PiP falls back to a centred crop and captions to the default height.")
    print(dst)


if __name__ == "__main__":
    main()

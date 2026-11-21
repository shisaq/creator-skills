#!/usr/bin/env python3
"""HyperFrames helpers: check, snapshot, render — with the known render hang worked around.

    python3 hf.py check  <project>                 lint + layout; prints errors and the warnings worth reading
    python3 hf.py snap   <project> 2,7.5,30 [-o DIR]  stills at those seconds + a contact sheet
    python3 hf.py render <project> <out.mp4>

Render hang: `hyperframes render` can sit forever at "Checking browser..." (an online browser check
that never returns, e.g. behind a proxy). If a downloaded chrome-headless-shell is in
~/.cache/hyperframes/chrome, it is passed via HYPERFRAMES_BROWSER_PATH so that check is skipped.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path


def env():
    e = dict(os.environ)
    if "HYPERFRAMES_BROWSER_PATH" not in e:
        shells = sorted(glob.glob(str(Path.home() / ".cache/hyperframes/chrome/chrome-headless-shell/*/*/chrome-headless-shell*")))
        shells = [s for s in shells if os.access(s, os.X_OK) and not s.endswith(".zip")]
        if shells:
            e["HYPERFRAMES_BROWSER_PATH"] = shells[-1]
    return e


def hf(*args, cwd):
    return subprocess.run(["npx", "--yes", "hyperframes", *args], cwd=cwd, env=env(), text=True, capture_output=True)


def check(proj):
    hf("check", "--json", cwd=proj)
    reports = sorted(glob.glob(str(Path(proj) / ".hyperframes/artifacts/checks/*.json")), key=os.path.getmtime)
    if not reports:
        sys.exit("check produced no report")
    d = json.load(open(reports[-1], encoding="utf-8"))
    rows = []

    def walk(o):
        if isinstance(o, dict):
            if "code" in o and "severity" in o:
                rows.append((o["severity"], o["code"], o.get("selector", ""), o.get("time", ""), (o.get("message") or "")[:160]))
            else:
                for v in o.values():
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    print("ok" if d.get("ok") else "NOT OK")
    for sev, code, sel, t, msg in rows:
        if sev == "error" or (sev == "warning" and code not in ("outside_safe_zone",)):
            print(f"  {sev} {code} {sel} @{t}: {msg}")
    skipped = sum(1 for r in rows if r[1] == "outside_safe_zone")
    if skipped:
        print(f"  ({skipped} outside_safe_zone warnings: expected for captions placed below the chin)")
    return d.get("ok")


def snap(proj, times, out):
    args = ["snapshot", "--at", times, "--no-end", "--timeout", "120000"]
    if out:
        args += ["-o", out]
    r = hf(*args, cwd=proj)
    lines = (r.stdout + r.stderr).strip().splitlines()
    print(lines[-1] if lines else "no output")


def render(proj, out):
    out = str(Path(out).expanduser().resolve())
    p = subprocess.Popen(["npx", "--yes", "hyperframes", "render", "-o", out], cwd=proj, env=env(), text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    last = -10
    for line in p.stdout:
        if line.startswith("@hf-progress"):
            try:
                pct = json.loads(line.split(" ", 1)[1]).get("pct", 0)
            except Exception:
                continue
            if pct >= last + 10:
                print(f"  {pct}%", flush=True)
                last = pct
        elif "Capturing frame" not in line and line.strip():
            print(line.rstrip(), flush=True)
    sys.exit(p.wait())


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, proj = sys.argv[1], str(Path(sys.argv[2]).expanduser().resolve())
    if cmd == "check":
        sys.exit(0 if check(proj) else 1)
    if cmd == "snap":
        out = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else None
        snap(proj, sys.argv[3], out)
    elif cmd == "render":
        render(proj, sys.argv[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()

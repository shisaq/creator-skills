#!/usr/bin/env python3
"""Keep files that several skills carry their own copy of identical.

Each skill folder must work on its own when copied, so shared code is duplicated on purpose.
Edit the canonical copy (left), then run:

    python3 tools/sync_shared.py          # copy canonical → every copy
    python3 tools/sync_shared.py --check  # only report copies that drifted (exit 1 if any)
"""

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = "plugins/{0}/skills/{0}/scripts"

SHARED = [
    # canonical                                           copies
    (f"{P.format('subtitle-toolkit')}/transcribe.py", [f"{P.format(n)}/transcribe.py" for n in
                                                     ("meeting-clipper", "selfmedia-video", "chapter-bar")]),
]
CORE = ["__init__.py", "base.py", "compose.py", "custom.py", "fonts.py", "look.py", "media.py"]
SHARED += [(f"{P.format('chapter-bar')}/core/{f}", [f"{P.format('mv-accents')}/core/{f}"]) for f in CORE]


def main():
    check = "--check" in sys.argv
    drift = 0
    for src, dsts in SHARED:
        s = ROOT / src
        for d in dsts:
            t = ROOT / d
            same = t.exists() and filecmp.cmp(s, t, shallow=False)
            if same:
                continue
            drift += 1
            if check:
                print(f"不一致：{d}（正本 {src}）")
            else:
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, t)
                print(f"已同步：{d}")
    if check:
        print("全部一致。" if not drift else f"{drift} 个副本和正本不一致，运行 `python3 tools/sync_shared.py` 同步。")
        sys.exit(1 if drift else 0)
    if not drift:
        print("全部一致，无需同步。")


if __name__ == "__main__":
    main()

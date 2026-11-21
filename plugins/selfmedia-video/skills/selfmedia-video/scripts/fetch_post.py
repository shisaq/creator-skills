#!/usr/bin/env python3
"""Fetch a public X (Twitter) post: full text, author, time, likes, avatar.

    python3 fetch_post.py https://x.com/<user>/status/<id> [--out DIR]

Writes <id>.post.json and <id>.avatar.jpg into --out (default: current directory). Uses the public
fxtwitter API (full text, including posts folded behind "Show more"), then X's own syndication
endpoint as a fallback (text may be truncated there). Translate the text yourself and fill the
"post" card in the spec; never put the English screenshot on screen with a caption under it.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

UA = {"User-Agent": "creator-skills/1.0"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    m = re.search(r"(?:x|twitter)\.com/([^/]+)/status/(\d+)", a.url)
    if not m:
        raise SystemExit("Not an X post URL")
    user, pid = m.groups()
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    post = None
    try:
        t = json.loads(get(f"https://api.fxtwitter.com/{user}/status/{pid}"))["tweet"]
        post = {"id": pid, "url": a.url, "name": t["author"]["name"], "handle": "@" + t["author"]["screen_name"],
                "text": t["text"], "created_at": t.get("created_at"), "likes": t.get("likes"),
                "replies": t.get("replies"), "avatar_url": t["author"].get("avatar_url", "").replace("_200x200", "_400x400"),
                "source": "fxtwitter"}
    except Exception as e:  # noqa: BLE001
        print(f"fxtwitter failed ({e}); trying syndication (text may be truncated)")
        d = json.loads(get(f"https://cdn.syndication.twimg.com/tweet-result?id={pid}&token=a"))
        post = {"id": pid, "url": a.url, "name": d["user"]["name"], "handle": "@" + d["user"]["screen_name"],
                "text": d["text"], "created_at": d.get("created_at"), "likes": d.get("favorite_count"),
                "replies": d.get("conversation_count"),
                "avatar_url": d["user"]["profile_image_url_https"].replace("_normal", "_400x400"),
                "source": "syndication", "truncated": bool(d.get("note_tweet"))}
    if post.get("avatar_url"):
        av = out / f"{pid}.avatar.jpg"
        av.write_bytes(get(post["avatar_url"]))
        post["avatar"] = av.name
    (out / f"{pid}.post.json").write_text(json.dumps(post, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(post, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

"""Find a bold CJK font on macOS / Windows / Linux without bundling one."""

from __future__ import annotations

import os
import platform
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

# Filename fragments in priority order (case-insensitive substring match on the file name).
UI_PATTERNS = [
    "notosanscjksc-bold", "sourcehansanssc-bold", "sourcehanscn-bold", "sourcehansanscn-bold", "思源黑体",
    "alibabapuhuiti", "阿里巴巴普惠体",
    "msyhbd", "hiragino sans gb", "pingfang", "stheiti medium",
    "notosanscjk-bold", "notosanscjksc-medium", "notosanscjk-medium", "msyh", "simhei",
    "wqy-zenhei", "wqy-microhei", "droidsansfallback",
]
TITLE_PATTERNS = ["优设标题黑", "youshebiaotihei", "notosanscjksc-black", "sourcehansanssc-heavy"]
BOLD_STYLES = ("bold", "w6", "semibold", "medium", "heavy", "black", "w7", "w8")


def font_dirs() -> list[Path]:
    home = Path.home()
    sysname = platform.system()
    if sysname == "Darwin":
        dirs = [home / "Library/Fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts"),
                Path("/System/Library/Fonts/Supplemental")]
    elif sysname == "Windows":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs = [windir / "Fonts"]
        if os.environ.get("LOCALAPPDATA"):
            dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts")
    else:
        dirs = [home / ".local/share/fonts", home / ".fonts", Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=1)
def _all_fonts() -> list[Path]:
    out = []
    for d in font_dirs():
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith((".ttf", ".otf", ".ttc", ".otc")):
                    out.append(Path(root) / f)
    return out


def _best_index(path: Path) -> int:
    """For .ttc collections pick the boldest Simplified-Chinese face."""
    if path.suffix.lower() not in (".ttc", ".otc"):
        return 0
    best, best_score = 0, -1
    for i in range(32):
        try:
            fam, style = ImageFont.truetype(str(path), 20, index=i).getname()
        except Exception:
            break
        s = (fam + " " + style).lower()
        score = 0
        if any(b in s for b in BOLD_STYLES):
            score += 2
        if " sc" in s or "gb" in s or "简" in s:
            score += 1
        if s.startswith("."):
            score -= 3
        if score > best_score:
            best, best_score = i, score
    return best


def _has_cjk(path: Path, index: int) -> bool:
    """Real CJK glyphs: '中' and '文' render to different, non-empty bitmaps (a missing glyph draws the same box twice)."""
    from PIL import Image, ImageDraw

    try:
        f = ImageFont.truetype(str(path), 40, index=index)
        imgs = []
        for ch in ("中", "文"):
            im = Image.new("L", (60, 60), 0)
            ImageDraw.Draw(im).text((5, 5), ch, font=f, fill=255)
            imgs.append(im)
        return bool(imgs[0].getbbox()) and imgs[0].tobytes() != imgs[1].tobytes()
    except Exception:
        return False


def _find(patterns: list[str]) -> tuple[Path, int] | None:
    files = _all_fonts()
    for pat in patterns:
        for f in files:
            if pat in f.name.lower():
                idx = _best_index(f)
                if _has_cjk(f, idx):
                    return f, idx
    return None


@lru_cache(maxsize=4)
def resolve(ui_override: str = "", title_override: str = "") -> dict:
    def use(path_str: str):
        p = Path(os.path.expanduser(path_str))
        if not p.is_file():
            raise SystemExit(f"style 里指定的字体文件不存在：{path_str}")
        return p, _best_index(p)

    ui = use(ui_override) if ui_override else _find(UI_PATTERNS)
    if not ui:
        raise SystemExit(
            "没找到能显示中文的字体。请下载免费的「思源黑体」（Source Han Sans SC Bold）安装，"
            "或在 plan.json 的 style.font 里填一个中文字体文件的完整路径。"
        )
    title = use(title_override) if title_override else (_find(TITLE_PATTERNS) or ui)
    return {"ui": ui, "title": title}


@lru_cache(maxsize=256)
def get(kind: str, size: int, ui_override: str = "", title_override: str = ""):
    path, idx = resolve(ui_override, title_override)[kind]
    return ImageFont.truetype(str(path), max(8, int(size)), index=idx)

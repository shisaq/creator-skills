"""Load effect classes the model wrote itself (a .py file next to the video), so the skill isn't limited to built-ins."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import traceback
from pathlib import Path


def load_class(file: str, cls_name: str, plan_dir: Path):
    path = Path(file).expanduser()
    if not path.is_absolute():
        path = (plan_dir / path).resolve()
    if not path.exists():
        raise SystemExit(f"自定义效果文件不存在：{path}")
    src = path.read_bytes()
    h = hashlib.sha1(src).hexdigest()[:12]
    mod_name = f"custom_fx_{h}"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception:
            raise SystemExit(f"自定义效果文件 {path.name} 加载出错：\n{traceback.format_exc(limit=3)}")
        sys.modules[mod_name] = mod
    cls = getattr(mod, cls_name, None)
    if cls is None:
        raise SystemExit(f"{path.name} 里没有叫 {cls_name} 的类。")
    return cls, h


def build(ctx, specs: list[dict], plan_dir: Path):
    out = []
    for s in specs or []:
        if not s.get("file") or not s.get("class"):
            raise SystemExit("custom 里每一项都要有 file（.py 文件）和 class（类名）。")
        cls, h = load_class(s["file"], s["class"], plan_dir)
        try:
            e = cls(ctx, s)
        except SystemExit:
            raise
        except Exception:
            raise SystemExit(f"自定义效果 {s['class']} 初始化出错：\n{traceback.format_exc(limit=3)}")
        e._src_hash = h
        out.append(e)
    return out


def smoke_test(els):
    """Draw a few frames of every element so code errors surface before a long render."""
    errs = []
    for e in els:
        for t in (e.start, (e.start + e.end) / 2, max(e.start, e.end - 0.01)):
            try:
                im = e.draw(t)
                if im.size != e.size and im.size != (e.w, e.h):
                    errs.append(f"{e.label}: draw() 返回的图是 {im.size}，应该是 {e.size}（用 self.blank() 起手）")
                    break
            except Exception:
                errs.append(f"{e.label} 在 t={t:.2f} 出错：\n{traceback.format_exc(limit=4)}")
                break
    return errs

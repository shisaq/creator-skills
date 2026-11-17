#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Form checks for short-video scripts and multi-platform publish copy.

    check.py script <口播稿.md|.txt>      spoken-script checks
    check.py copy   <社交平台文案.md>      per-platform publish-copy checks
    check.py ... --extra-banned 词1,词2   add account-specific banned words

Checks form only: banned AI patterns, jargon, sentence and opening length, estimated
duration, platform limits, traffic-diversion words. Whether the hook actually lands is
for a human (or the model) to judge.
Exit code: 0 = no FAIL, 1 = has FAIL, 2 = file/structure problem.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

# (pattern, label, level). FAIL = never acceptable; WARN = usually rewrite.
AI_PATTERNS = [
    (r"不是[^。！？!?\n]{0,30}?而是", "「不是…而是…」", "FAIL"),
    (r"不是[^。！？!?\n，,]{1,20}[，,]\s*(?:就)?是", "「不是…，是…」", "FAIL"),
    (r"与其[^。！？!?\n]{0,25}?不如", "「与其…不如…」", "FAIL"),
    (r"不仅[^。！？!?\n]{0,30}?(?:更|还|也)", "「不仅…更/还…」", "WARN"),
    (r"既(?!然)[^。！？!?\n]{1,15}?又", "「既…又…」", "WARN"),
    (r"真正的(?:价值|关键|意义|核心)(?:在于|是)", "「真正的…在于」", "WARN"),
    (r"这背后(?:反映|折射|体现)", "「这背后反映」", "WARN"),
    (r"这意味着", "「这意味着」", "WARN"),
    (r"在这个过程中", "「在这个过程中」", "WARN"),
    (r"对于[^，。！？\n]{1,12}来说", "「对于…来说」", "WARN"),
    (r"随着[^，。！？\n]{1,15}的(?:发展|普及|到来)", "「随着…的发展」", "WARN"),
    (r"值得一提的是|不难发现|毋庸置疑|众所周知", "套话", "WARN"),
    (r"总而言之|综上所述|总的来说", "总结套话", "WARN"),
    (r"让我们一起", "「让我们一起」", "WARN"),
]
JARGON = ["赋能", "闭环", "抓手", "底座", "范式", "生态", "沉淀", "链路", "颗粒度", "打通", "一站式",
          "全方位", "全链路", "深度融合", "降本增效", "提质增效", "助力", "数字化转型", "智能化升级",
          "重塑", "颠覆", "革命性", "划时代"]
HYPE = ["彻底颠覆", "完全替代", "百分百", "零成本", "躺赚", "封神", "杀疯了", "炸裂"]
WRITTEN = ["因此", "然而", "此外", "并且", "从而", "亦即", "予以", "进行了", "能够", "是否", "若是", "如若"]

TAG = re.compile(r"#[^\s#]+")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF"
                   "\U00002190-\U000021FF\U00002B00-\U00002BFF‼⁉①-⓿️❤]")
DRAIN_HARD = ["扫码", "加微信", "公众号", "http", "搜一搜", "私信我", "二维码", "加V", "vx"]
DRAIN_SOFT = ["官网", "下载"]
OTHER_PLATFORMS = ["微信", "抖音", "淘宝", "视频号", "B站", "b站", "快手"]
CHARS_PER_SEC = 4.3  # ~260 Chinese characters per minute

ok = True


def say(level: str, field: str, msg: str) -> None:
    global ok
    if level == "FAIL":
        ok = False
    icon = {"OK": "  ✅", "WARN": "  ⚠️ ", "FAIL": "  ❌"}[level]
    print(f"{icon} {field}: {msg}")


def n(s: str) -> int:
    return len(re.sub(r"\s+", "", s))


def width(s: str) -> int:
    return sum(2 if "⺀" <= c <= "鿿" or "＀" <= c <= "￯" else 1 for c in s.strip())


def style_checks(name: str, text: str, extra: list[str], spoken: bool) -> None:
    found = False
    for pat, label, level in AI_PATTERNS:
        for m in re.finditer(pat, text):
            found = True
            say(level, f"{name}·AI句式", f"{label}：…{m.group(0)[:30]}…")
    jar = [w for w in JARGON if w in text]
    if len(jar) >= 2 or any(text.count(w) > 1 for w in jar):
        say("WARN", f"{name}·技术腔", f"{jar}（每条最多一个，且要紧跟具体场景）")
        found = True
    hype = [w for w in HYPE if w in text]
    if hype:
        say("WARN", f"{name}·夸张", f"{hype}")
        found = True
    bad = [w for w in extra if w and w in text]
    if bad:
        say("FAIL", f"{name}·账号禁用词", f"{bad}")
        found = True
    if text.count("——") > 1:
        say("WARN", f"{name}·破折号", f"{text.count('——')} 处（最多 1 处）")
        found = True
    if spoken:
        written = [w for w in WRITTEN if w in text]
        if written:
            say("WARN", f"{name}·书面词", f"{written}（念出来不像说话，见 spoken.md）")
            found = True
    if not found:
        say("OK", f"{name}·文风", "没发现禁用句式和技术腔")


# --------------------------------------------------------------------------- script mode


def extract_script(md: str) -> str:
    """Use the `## 口播稿…` section if present, else the whole file minus markdown chrome."""
    m = re.search(r"^##\s*口播稿[^\n]*\n(.*?)(?=^##\s|\Z)", md, flags=re.M | re.S)
    body = m.group(1) if m else md
    lines = [l for l in body.splitlines()
             if l.strip() and not l.lstrip().startswith(("#", ">", "|", "```", "- [", "**"))]
    return "\n".join(lines)


def check_script(path: Path, extra: list[str]) -> None:
    text = extract_script(path.read_text(encoding="utf-8-sig"))
    if not text.strip():
        print("❌ 没读到口播正文")
        sys.exit(2)
    print(f"检查口播稿 {path.name}")
    chars = n(re.sub(r"[，。！？、；：,.!?;:\"'“”‘’（）()…—]", "", text))
    secs = chars / CHARS_PER_SEC
    say("OK", "长度", f"约 {chars} 字，按正常语速约 {secs:.0f} 秒")

    sentences = [s.strip() for s in re.split(r"[。！？!?\n]+", text) if s.strip()]
    first = sentences[0] if sentences else ""
    fc = n(first)
    say("OK" if fc <= 15 else ("WARN" if fc <= 20 else "FAIL"), "第一句",
        f"{fc} 字（前 3 秒约 12–15 字）：{first[:30]}")
    long_ones = [s for s in sentences if n(s) > 25]
    if long_ones:
        say("WARN", "长句", f"{len(long_ones)} 句超过 25 字，念着要换气：" +
            "；".join(s[:20] + "…" for s in long_ones[:5]))
    else:
        say("OK", "长句", "没有超过 25 字的句子")

    # Flat stretches: >40 chars (~9s) between "stimuli" (number, question, line break of a new point)
    paras = [p for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    flat = [p for p in paras if n(p) > 40 and not re.search(r"[0-9０-９一二三四五六七八九十百千万]|[?？！!]", p)]
    if flat:
        say("WARN", "平段", f"{len(flat)} 段超过 40 字且没有数字/提问/感叹，可能是让人划走的平地")
    last = sentences[-1] if sentences else ""
    if not re.search(r"[?？]", "".join(sentences[-2:])):
        say("WARN", "结尾", f"最后两句没有提问，评论口子不明显：{last[:30]}")
    if re.search(r"总结一下|总的来说|以上就是|今天就分享到这", text):
        say("WARN", "结尾", "出现总结式收尾，这里最容易掉人")
    style_checks("口播", text, extra, spoken=True)


# --------------------------------------------------------------------------- copy mode


def parse_copy(md: str) -> dict[str, str]:
    """Split by `## 平台` / `### 子节` / `**字段**` into {"平台·子节·字段": body}."""
    out: dict[str, str] = {}
    section = sub = field = None
    buf: list[str] = []

    def flush() -> None:
        if field and buf:
            body = "\n".join(buf).strip()
            if body:
                out[f"{section}{'·' + sub if sub else ''}·{field}"] = body

    for line in md.splitlines():
        s = line.strip()
        if s.startswith("## "):
            flush(); buf, field, sub = [], None, None
            section = s[3:].strip()
        elif s.startswith("### "):
            flush(); buf, field = [], None
            sub = s[4:].strip()
        elif re.match(r"\*\*(.+?)\*\*", s):
            flush(); buf = []
            m = re.match(r"\*\*(.+?)\*\*[（(]?[^：:]*[）)]?[：:]?\s*(.*)", s)
            field = m.group(1).strip()
            if m.group(2):
                buf.append(m.group(2))
        elif s == "---" or s.startswith(">") or s.startswith("# "):
            continue
        elif field:
            buf.append(line)
    flush()
    return out


def get(fields: dict[str, str], *keys: str):
    for k, v in fields.items():
        if all(key in k for key in keys):
            return v
    return None


def title_options(t: str) -> list[str]:
    """A title field may hold one title or a numbered list of 3 options with notes."""
    items = re.findall(r"^\s*\d+[.、)]\s*(.+)$", t, flags=re.M)
    items = items or [t]
    cleaned = []
    for it in items:
        it = re.sub(r"[（(]\s*赌[:：][^）)]*[）)]", "", it)
        it = re.sub(r"←.*$", "", it)
        cleaned.append(it.strip())
    return [c for c in cleaned if c]


def check_titles(label: str, t: str | None, limit: int, unit: str = "字") -> None:
    if not t:
        return
    for i, opt in enumerate(title_options(t), 1):
        c = n(opt)
        say("OK" if c <= limit else "FAIL", f"{label}{i if len(title_options(t)) > 1 else ''}",
            f"{c} {unit}（≤{limit}）：{opt[:24]}")


def drain(name: str, text: str, other_platforms: bool = False) -> None:
    hard = [w for w in DRAIN_HARD if w.lower() in text.lower()]
    soft = [w for w in DRAIN_SOFT if w in text]
    other = [w for w in OTHER_PLATFORMS if w in text] if other_platforms else []
    if hard:
        say("FAIL", f"{name}·引流", f"出现 {hard}，会被限流")
    elif other:
        say("WARN", f"{name}·引流", f"提到其他平台 {other}")
    elif soft:
        say("WARN", f"{name}·引流", f"出现 {soft}，如果是引流就删")


def check_copy(path: Path, extra: list[str]) -> None:
    f = parse_copy(path.read_text(encoding="utf-8-sig"))
    if not f:
        print("❌ 没解析出任何字段——检查是否按 publish.md 的输出模板书写")
        sys.exit(2)
    print(f"检查发布文案 {path.name}")
    sections = {k.split("·")[0] for k in f}

    if any("视频号" in s for s in sections):
        print("\n视频号")
        st = get(f, "视频号", "短标题")
        if st:
            c = n(st)
            say("OK" if 6 <= c <= 16 else "WARN", "短标题", f"{c} 字（6–16）")
        body = get(f, "视频号", "描述")
        if body:
            text, tags = TAG.sub("", body).strip(), TAG.findall(body)
            c = n(re.sub(r"[A-Za-z]", "", text))
            say("OK" if 100 <= c <= 180 else "WARN", "描述字数", f"{c} 字（100–180，不计英文）")
            say("OK" if 3 <= len(tags) <= 6 else "WARN", "话题", f"{len(tags)} 个（3–6）")
            say("FAIL" if "\n" in text else "OK", "分行", "要一整段" if "\n" in text else "单段")
            e = EMOJI.findall(text)
            say("FAIL" if e else "OK", "emoji", "".join(e) if e else "无")
            b = text.count("！") + text.count("!")
            say("OK" if b <= 1 else "FAIL", "感叹号", f"{b} 个（≤1）")
            style_checks("视频号", text, extra, spoken=False)

    if any("抖音" in s for s in sections):
        print("\n抖音")
        check_titles("标题", get(f, "抖音", "标题"), 30)
        body = get(f, "抖音", "描述")
        if body:
            text, tags = TAG.sub("", body).strip(), TAG.findall(body)
            c = n(text)
            say("OK" if 40 <= c <= 180 else "WARN", "描述字数", f"{c} 字（40–180）")
            say("OK" if 3 <= len(tags) <= 5 else "WARN", "话题", f"{len(tags)} 个（3–5）")
            drain("抖音", text)
            if not re.search(r"[?？]", text):
                say("WARN", "互动", "没有提问句")
            style_checks("抖音", text, extra, spoken=False)

    if any("小红书" in s for s in sections):
        print("\n小红书")
        check_titles("标题", get(f, "小红书", "标题"), 20)
        body = get(f, "小红书", "正文")
        if body:
            text, tags = TAG.sub("", body).strip(), TAG.findall(body)
            c = n(text)
            say("FAIL" if c > 1000 else ("OK" if 250 <= c <= 450 else "WARN"), "正文字数",
                f"{c} 字（建议 250–450，上限 1000）")
            say("OK" if 5 <= len(tags) <= 8 else "WARN", "话题", f"{len(tags)} 个（5–8）")
            drain("小红书", text, other_platforms=True)
            if not re.search(r"[?？]", text):
                say("WARN", "互动", "没有提问句")
            style_checks("小红书", text, extra, spoken=False)

    if any("B 站" in s or "B站" in s for s in sections):
        print("\nB 站")
        t = get(f, "B 站", "标题") or get(f, "B站", "标题")
        check_titles("标题", t, 80)
        tags = get(f, "B 站", "标签") or get(f, "B站", "标签")
        if tags:
            items = [x.strip() for x in re.split(r"[、,，\n]", tags) if x.strip()]
            say("OK" if len(items) <= 10 else "FAIL", "标签", f"{len(items)} 个（≤10）")
            long = [x for x in items if len(x) > 20]
            if long:
                say("FAIL", "标签长度", f"{long} 超过 20 字")
        body = get(f, "B 站", "简介") or get(f, "B站", "简介")
        if body:
            say("OK" if n(body) <= 2000 else "FAIL", "简介字数", f"{n(body)} 字（≤2000）")
            style_checks("B 站", body, extra, spoken=False)

    if any("YouTube" in s for s in sections):
        print("\nYouTube")
        for label, tk, dk in (("中文版", "标题", "描述"), ("English", "Title", "Description")):
            t, d = get(f, "YouTube", label, tk), get(f, "YouTube", label, dk)
            if t:
                for opt in title_options(t):
                    w, L = width(opt), len(opt)
                    say("FAIL" if L > 100 else ("OK" if w <= 70 else "WARN"), f"{label} 标题",
                        f"显示宽度 {w}（尽量 ≤70），{L} 字符（≤100）")
            if d:
                tags = TAG.findall(d)
                say("OK" if 3 <= len(tags) <= 5 else "WARN", f"{label} hashtag", f"{len(tags)} 个（3–5）")
                if len(d) > 5000:
                    say("FAIL", f"{label} 描述", "超过 5000 字符")
                if label == "中文版":
                    style_checks("YouTube 中文", d, extra, spoken=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["script", "copy"])
    ap.add_argument("file")
    ap.add_argument("--extra-banned", default="", help="Comma-separated account-specific banned words")
    args = ap.parse_args()
    path = Path(args.file)
    if not path.exists():
        print(f"❌ 找不到文件: {path}")
        sys.exit(2)
    extra = [w.strip() for w in re.split(r"[,，]", args.extra_banned) if w.strip()]
    (check_script if args.mode == "script" else check_copy)(path, extra)
    print("\n" + ("✅ 形式检查通过（钩子和情绪还要自己再读一遍）" if ok else "❌ 有 FAIL 项需要修"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

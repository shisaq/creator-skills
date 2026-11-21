# 包装规格 spec.json

`build.py` 只读这一个文件。路径都相对 spec.json 所在目录。时间全部是**成片时间（秒）**，从成片的 `words.json` 查"说到某个词"的时间。

## 顶层

```jsonc
{
  "video": "成片.mp4",                 // 精修后的成片（SDR）
  "face": "成片.face.json",            // face.py 输出
  "captions": "captions.json",         // captions.py align 输出
  "palette": {"a": "#8BD400", "b": "#FF3B4E", "accent": "#FFC72C"},   // 两方对立色 + 强调色
  "highlight": {"a": ["黄仁勋"], "b": ["乔丹", "公牛"], "accent": ["1963年2月17日", "复出"]},
  "background": "court",               // 小窗段的背景：court（按 FIBA 比例画的半场线）| plain
  "bgm": {"file": "/path/music.mp3", "volume": 0.13, "offset": 0},
  "sfx": true,                         // 小窗切换、数字揭晓、盖章、结尾卡自动配合成音效
  "hook":   {...}, "pip": [...], "punch": [...], "finale": {...}, "cta": {...}, "cover": {...}
}
```

**富文本**：`{a:文字}` `{b:文字}` `{accent:文字}` `{muted:文字}` 上色，`{u:文字}` 下划线，可组合 `{accent,u:卷土重来}`，`\n` 换行。

## hook — 开头钩子（全屏，第 0 帧就在）

```json
"hook": {"tag": "马斯克评黄仁勋离职", "lines": ["逼走{a:黄仁勋}", "= 让{b:乔丹}离开{b:公牛}"], "until": 5.4}
```
每行 ≤ 8 个汉字（92px）。标题通常就是选定的视频标题。

## pip — 小窗段落

```json
"pip": [{"start": 5.4, "end": 16.3, "cards": [ {卡片}, {卡片} ]}]
```
`start/end` 是人缩进右上角小窗的时间（切换动画 0.6s）。段内卡片首尾相接覆盖整段。每张卡都有左上角**表头**：
`"tag"`（金色胶囊小标签）、`"title"`（1–2 行大字，每行 ≤ 7 字最好）、`"note"`（小字说明，如"原帖 · 中文译文"）。

### news — 新闻标题卡（按原媒体版式重做成中文）
```json
{"type": "news", "start": 5.4, "end": 10.0, "tag": "TechCrunch · 11.18", "title": ["马斯克", "怎么说？"], "note": "报道标题 · 中文译文",
 "logo": "img/tclogo.png", "color": "#0A8935", "bar": "#212623", "category": "AI",
 "headline": ["马斯克称，赶走黄仁勋就像", "「把迈克尔·乔丹踢出你的球队」"], "byline": "Amanda Silberling — 2026年11月18日"}
```
`color` / `bar` 取原页面的主色和顶栏色（截一张图取色）；`logo` 从原页面截图裁下来。

### post — 社交帖子卡（X 版式，中文正文）
```json
{"type": "post", "start": 10.0, "end": 16.3, "tag": "X · 11.19", "title": ["马斯克", "原话"], "note": "原帖 · 中文译文\n出自 DealBook 峰会发言",
 "avatar": "img/<id>.avatar.jpg", "avatar_radius": "8px", "name": "The Kobeissi Letter", "handle": "@KobeissiLetter",
 "verified": "gold", "paragraphs": ["……", "……"], "time": "上午9:54 · 2026年11月19日", "likes": "6K"}
```
`fetch_post.py` 拿到的是全文（包括被"显示更多"折叠的部分）；**逐段完整翻译**，不要删减原话。

### pair — 两人对照 + 数值揭晓 + 盖章
```json
{"type": "pair", "start": 38.55, "end": 49.92, "tag": "彩蛋 ①", "title": ["两个 {accent:GOAT}", "{u:同一天生日}"],
 "people": [{"img": "img/jensen.jpg", "name": "黄仁勋", "color": "a"}, {"img": "img/jordan.jpg", "name": "迈克尔·乔丹", "color": "b"}],
 "label": "出生日期", "hidden": "????.??.??", "value": "1963.02.17", "enter": [40.06, 41.2], "reveal": 45.5,
 "stamp": {"text": "同年同月同日", "at": 47.95}}
```
两人数值不同时在 people 里各写 `"value"`。

### rows — 对比行（头像 + 名字 + 一句话，逐行出现）
```json
{"type": "rows", "start": 49.92, "end": 63.25, "tag": "彩蛋 ②", "title": ["为什么用{b:乔丹}", "不用{muted:乔布斯}？"],
 "rows": [{"img": "img/jordan.jpg", "name": "乔丹", "color": "b", "text": "巅峰时离开公牛，后来复出", "at": 52.4}, …]}
```
最多 4 行。

### timeline — 时间轴（节点随口播逐个出现）
```json
{"type": "timeline", "start": 63.25, "end": 88.25, "tag": "乔丹的第一次离开", "title": ["离开两年", "{u:再回来夺冠}"],
 "nodes": [{"at": 64.44, "when": "1991–93", "text": "第一次三连冠", "color": "accent"}, {"at": 66.22, "when": "1993.07", "text": "父亲遇害"}, …]}
```
最多 7 个节点。没有 `color` 的节点是普通事件，有颜色的是转折点。日期必须核实。

### image — 一张截图（实在无法重做时才用）
```json
{"type": "image", "start": …, "end": …, "src": "img/shot.png", "tag": "…", "title": ["…"]}
```

## punch — 推近强调（全屏段，整片 0–2 次）
```json
"punch": [{"at": 37.06, "until": 38.55}]
```
以脸为中心放大到 1.1。`until` 正好是小窗开始时间的话，直接接入小窗。

## finale — 结尾大字（全屏顶部）
```json
"finale": {"lines": ["你可以离开", "但可以{accent,u:卷土重来}"], "at": [92.9, 95.14]}
```
每行在 `at` 对应的时间出现，最后一行带一点放大。

## cta — 结尾互动卡（盖住最后几秒）
```json
"cta": {"at": 96.9, "hold": 2.7, "images": ["img/a.jpg", "img/b.jpg"], "lines": ["你觉得{a:黄仁勋}", "会像{b:乔丹}一样回来吗？"],
        "button": "评论区聊聊", "credits": ["图片：作者 (CC BY-SA 4.0)…", "报道与原帖译自：…"]}
```
`hold` 是成片结束后再停留的秒数。用了 CC 授权图片就**必须**写 `credits`。

## cover — 3:4 封面（cover.py 用）
```json
"cover": {"frame": 88.6, "tag": "…", "lines": ["逼走{a:黄仁勋}", "＝让{b:乔丹}离开{b:公牛}"], "sub": "这个比喻里，藏着{u:两个彩蛋}",
          "people": ["img/jensen.jpg", "img/jordan.jpg"], "badge": "同年同月同日生", "value": "1963.02.17"}
```
`frame` 挑笑着、睁眼、嘴型好看的一帧。

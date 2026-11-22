# 自己写效果

渲染器只要求一件事：给定时间 `t`，返回你负责的那块矩形区域的 RGBA 图片。逐帧调用、编码、缓存、合成都由渲染器处理。

完整的范例：`examples/rising_notes.py`（飘音符）。内置效果在 `scripts/effects.py`，每个都不到 80 行，也都可以照着改。

## 骨架

```python
# my_fx.py —— 放在视频旁边；方案里写 {"type": "custom", "file": "my_fx.py", "class": "MyFx", ...你的参数}
import math, random
from PIL import ImageDraw
from core.base import Element, rgba, mix, hex_rgb, clamp, ease_out, ease_out_back

class MyFx(Element):
    kind = "my_fx"
    layer = 20            # 叠放顺序：律动 10，粒子 12，歌名卡 40，片尾卡 90
    # scale = 0.5         # 柔和的或全屏的效果用半分辨率，速度快 4 倍；有文字、有细线的别用

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        m = ctx.music
        self.hits = m.hits("big", spec.get("sync", "auto"), spec.get("from"), spec.get("to"))
        self.start, self.end = m.span(spec.get("from"), spec.get("to"))
        # 随机性要固定：用 random.Random(种子)，同一份方案每次渲染结果都一样，缓存才有效
        # 只框住要画的区域（原视频像素），越小越快
        self.fit_region(x0, y0, x1, y1)
        self.label = "我的效果"

    def draw(self, t):
        im = self.blank()                   # 透明画布，大小 = 区域 × scale
        d = ImageDraw.Draw(im)
        # 画的时候：坐标 = (原视频坐标 - self.x/self.y) × self.scale
        return im
```

## ctx.music（音乐）

| 调用 | 返回 |
|---|---|
| `m.hits(kind, sync, from, to)` | `[(时间, 强度 0..1), ...]`。kind：`beat` 每拍（重拍 1.0，其余 0.55）、`down` 只要重拍、`note` 音符起音、`big` 重拍或最强的音符。sync：`auto` / `beats` / `onsets` |
| `m.envelope(t, hits, decay=0.22)` | 0..1，每次命中时跳到最高，再按指数衰减。做「呼吸」「闪动」就用它 |
| `m.energy(t)` | 0..1，t 附近的响度。用它让效果在安静段落自动变弱 |
| `m.last_hit(t, hits)` | 最近一次命中 `(时间, 强度)`，或 `None`。用来做「从命中那一刻开始播放的小动画」 |
| `m.span(from, to)` | 把 null 换成音乐的实际起止时间 |
| `m.bpm` `m.steady` `m.regions` | 速度、节拍稳不稳、有音乐的区间 |

常见写法：
- **「每次命中播放一段小动画」**：在 `__init__` 里为每个 hit 预先生成参数，`draw` 里用 `t - hit_time` 作为本地时间，只画最近约 1 秒内的那些（参考 Sparkles 和 RisingNotes 用 `bisect` 的写法）
- **「持续的呼吸」**：`level = m.envelope(t, hits, decay) * (0.4 + 0.6 * m.energy(t))`，用 level 控制透明度或大小

## ctx（画面）

| 名字 | 是什么 |
|---|---|
| `ctx.W` `ctx.H` `ctx.u` `ctx.portrait` `ctx.duration` | 画面宽高、尺寸倍数（短边/1080，所有尺寸都乘它）、是否竖屏、时长 |
| `ctx.accent` `ctx.dark` `ctx.light` | 方案里的主色、深色，以及米白色 |
| `ctx.font("ui" 或 "title", 字号)` | 自动找好的中文字体，字号是 1080p 单位 |

## 品质要求

- 效果要有「起、停、收」：出现 0.1–0.3 秒，用 `ease_out` 或 `ease_out_back`；淡出比出现慢
- 粒子和形状的数量、大小、速度都乘以 `ctx.u`
- 透明度一般不要满格，220 左右更柔和；大面积效果的透明度要更低
- 写完先跑 `mv.py check`，它会在 3 个时间点试画并报告错误；再用 `still` 看静帧，最后 render 看动态

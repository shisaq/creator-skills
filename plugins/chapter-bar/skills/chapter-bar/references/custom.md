# 自己写章节条样式

渲染器只要求一件事：给定时间 `t`，返回你负责的那块矩形区域的 RGBA 图片。逐帧调用、编码、缓存、合成、音效都由渲染器处理。

## 骨架

```python
# my_bar.py —— 放在视频旁边，方案里写 "custom": [{"file": "my_bar.py", "class": "MyBar", ...}]
from PIL import ImageDraw
from bars import ChapterBase                       # 章节计算都在这里
from core.base import rgba, mix, clamp, ease_out, ease_out_back

class MyBar(ChapterBase):
    def __init__(self, ctx, spec):
        super().__init__(ctx, spec, 60)            # 60 = 条的高度（1080p 单位，会自动乘 ctx.u）
        u = ctx.u
        self.f = ctx.font("ui", 24)                # "ui" 粗黑体 / "title" 标题字体；字号也是 1080p 单位
        # 区域越小渲染越快：只框住你要画的地方（原视频像素）
        self.fit_region(0, self.bar_y, ctx.W, self.bar_y + self.bh)
        self.label = "我的章节条"                   # 检查图上显示的名字

    def draw(self, t):
        im = self.blank()                          # 透明画布，大小 = 区域大小
        d = ImageDraw.Draw(im)
        i = self.index_at(t)                       # 当前第几章（从 0 开始）
        p = self.progress_in(t)                    # 本章进度 0..1
        # 坐标要减去 self.x / self.y，换成区域内的坐标
        ...
        return im
```

## 能用的东西

| 名字 | 是什么 |
|---|---|
| `self.segs` | `[(start, end, title), ...]` 每一章的起止时间和名字 |
| `self.index_at(t)` / `self.progress_in(t)` / `self.changed_ago(t)` | 当前章、本章进度、离换章过去了几秒（用来做换章动画） |
| `self.x_of(time)` | 时间换算成整条宽度上的 x 坐标 |
| `self.bar_y` / `self.bh` / `self.position` | 按 `position`（top/bottom）算好的条的 y 坐标、高度、位置 |
| `ctx.W` `ctx.H` `ctx.u` `ctx.portrait` | 画面宽高、尺寸倍数（短边/1080）、是否竖屏 |
| `ctx.accent` `ctx.dark` `ctx.light` | 方案里的主色、深色，以及米白色（RGB 元组） |
| `ctx.font(kind, size)` | 自动找好的中文字体 |
| `rgba(color, alpha)` `mix(a, b, k)` | 颜色加透明度、两色混合 |
| `ease_out` `ease_out_back` `ease_in_out` `clamp` | 缓动函数和数值截断 |
| `self.sfx.append((时间, "whoosh"/"pop"/"ding", 音量))` | 在某个时间点加音效 |
| `self.scale = 0.5` | 柔和的大面积效果可以用半分辨率渲染，速度快 4 倍；有文字的别用 |

内置的 `TabsBar`、`LineBar`、`Announce` 在 `scripts/bars.py` 里，是最好的参考：每个都不到 70 行。

## 设计提醒

- 尺寸都乘以 `ctx.u`，这样同一份代码在 1080p 和 4K、横屏和竖屏上看起来一样
- 动画要短：出现 0.25–0.45 秒，用 `ease_out` 或 `ease_out_back`；消失 0.3 秒。章节条本身要稳定，不要一直动
- 文字一定要有深色底或描边，因为视频画面的亮度不可预测
- 写完先跑 `chapters.py check`，它会在 3 个时间点试画；再用 `still` 看效果

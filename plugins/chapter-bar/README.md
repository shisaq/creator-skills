# chapter-bar · 章节进度条

给讲解、教学、录屏视频加章节进度条，让观众一眼看到「一共讲哪几块，现在讲到哪了」。

- AI 读字幕来划分章节、起章节名（没有字幕就在本地自动转写一份），再看画面选位置和配色
- 两种成品样式：**tabs**（深色整条，每章都标名字）和 **line**（极简细线，换章时浮出小标签）；长教程还可以打开换章大字卡
- 想要别的样子，AI 可以自己写新样式
- 同时导出 YouTube 章节文字，可以直接贴进简介

macOS 和 Windows 都能用，视频在本地处理，不上传。不需要预装 Python 或 ffmpeg。

## 安装

1. 装 uv（每台电脑只装一次）。macOS 运行 `curl -LsSf https://astral.sh/uv/install.sh | sh`；Windows 在 PowerShell 里运行 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. 装 skill：
   - Claude Code：`/plugin marketplace add shisaq/creator-skills`，然后 `/plugin install chapter-bar@creator-skills`
   - 其他 AI 工具（Codex、Cursor、Gemini CLI 等）：把 `skills/chapter-bar` 文件夹放进这个工具的 skills 目录。工具不支持 skill 的话，就把 `SKILL.md` 的内容发给它

## 用法

跟 AI 说：

> 给 `教程.mp4` 加个章节进度条，字幕在 `教程.srt`

它会读字幕、划分章节、出几张预览图给你看，你确认后再出片。导出的文件都在视频旁边：

- `教程_章节版.mp4`：成片
- `教程_检查图.jpg`：检查图
- `教程_YouTube章节.txt`：YouTube 章节文字

用 Final Cut、Premiere 或达芬奇的话，可以让它导出带透明通道的叠加层，放到剪辑软件里继续调。

技术说明：Pillow 逐帧画出带透明通道的片段，再用 ffmpeg 合成，没有 Node 或浏览器依赖。

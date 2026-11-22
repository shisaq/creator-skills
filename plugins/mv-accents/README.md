# mv-accents · 演奏视频的音乐特效

给弹琴、弹唱、任何乐器的演奏视频加跟着音乐走的点缀：边框随节拍呼吸、重拍迸发闪光粒子、音符飘起、歌名卡、片尾卡。AI 也可以照着这首歌的气质写全新的效果。

- 节拍分析：速度、重拍、强弱段落；自由速度的钢琴独奏会自动改成跟着音符起音走
- AI 先看画面，避开手、琴键和脸；配色从画面里取；效果跟着段落有起伏（安静段落收着，高潮再放开）
- 你说「副歌再强一点」「别挡手」，它就去调

macOS 和 Windows 都能用，视频在本地处理，不上传。不需要预装 Python 或 ffmpeg。

## 安装

1. 装 uv（每台电脑只装一次）。macOS 运行 `curl -LsSf https://astral.sh/uv/install.sh | sh`；Windows 在 PowerShell 里运行 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. 装 skill：
   - Claude Code：`/plugin marketplace add shisaq/creator-skills`，然后 `/plugin install mv-accents@creator-skills`
   - 其他 AI 工具（Codex、Cursor、Gemini CLI 等）：把 `skills/mv-accents` 文件夹放进这个工具的 skills 目录。工具不支持 skill 的话，就把 `SKILL.md` 的内容发给它

## 用法

跟 AI 说：

> 给 `童年钢琴.mp4` 加点跟节奏的特效，歌名是《童年》

它会先说清楚设计思路（哪段放什么效果、为什么），再出预览和成片 `童年钢琴_特效版.mp4`。看完成片后告诉它哪里要调就行。

技术说明：节拍分析用纯 numpy 实现（频谱通量起音、自相关求速度、动态规划追拍）；画面用 Pillow 逐帧渲染带透明通道的片段，再用 ffmpeg 合成。

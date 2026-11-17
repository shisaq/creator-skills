# creator-skills

给内容创作者用的 Claude Code 技能合集。macOS 和 Windows 通用，不需要预装 Python、ffmpeg 或转写软件；视频和音频都在本地处理，不会上传。

| 插件 | 做什么 |
|---|---|
| [meeting-clipper](plugins/meeting-clipper) | 把会议、直播、分享的长录像切成能单独发布的片段：本地转写 → 挑金句/观点/案例/干货并打分 → 确认后精确切片，每条附对齐字幕和一份交接文档 |
| [subtitle-toolkit](plugins/subtitle-toolkit) | 字幕工具箱：从视频出字幕、润色识别错误（时间轴一帧不动）、翻译成英文等语言、生成双语字幕或直接写进 Arctime 工程 |
| [short-video-writer](plugins/short-video-writer) | 短视频写手：围绕前 3 秒钩子、完播率、情绪和反差写口播稿；写视频号、抖音、小红书、B 站、YouTube 的发布文案；避开一眼 AI 的句式 |

## 安装

**1. 装 uv**（每台电脑一次，它替这些技能管理 Python 和依赖）

- macOS：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows（PowerShell）：`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

装完重开终端。

**2. 在 Claude Code 里添加插件市场，挑需要的装**

```
/plugin marketplace add shisaq/creator-skills
/plugin install meeting-clipper@creator-skills
/plugin install subtitle-toolkit@creator-skills
/plugin install short-video-writer@creator-skills
```

以后更新：`/plugin marketplace update creator-skills`

不用插件也行：把 `plugins/<插件>/skills/<技能>` 文件夹复制到 `~/.claude/skills/`（Windows 是 `C:\Users\<用户名>\.claude\skills\`），重启 Claude Code。

## 用法

装好后直接用大白话说，Claude 会自己调用对应的技能：

- 「帮我把 `直播回放.mp4` 切成短视频片段」
- 「这个视频出一份字幕，再翻成英文」
- 「`字幕.srt` 里好多错字，帮我改一下」
- 「帮我写一条讲 AI 省钱技巧的口播稿，60 秒」
- 「这条视频要发抖音和小红书了，配个文案」

## 一些设计

- **本地转写**：sherpa-onnx + SenseVoice，不依赖 PyTorch，Win/Mac 都有现成安装包；中文准确，支持中英混说，自带标点。模型约 240MB，第一次用时自动下载（国内走 ModelScope，海外设 `MEETING_CLIPPER_REGION=global`），多个插件共用一份。
- **时间轴交给脚本**：字幕润色和翻译时，模型只写文字，时间码由脚本按原文件重组，条数和时间永远不会被改乱。
- **术语表和账号档案**：字幕技能会读你项目里的 `术语表.md`，写作技能会读 `账号档案.md`。这些属于你自己的数据，放在你的项目目录里，不放进本仓库。
- **去 AI 味**：short-video-writer 自带禁用句式清单；如果你装了 [Humanizer-zh](https://github.com/op7418/Humanizer-zh)，会自动用它再把关一次。

## 许可

MIT

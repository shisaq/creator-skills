# meeting-clipper

Claude Code 的会议视频切片 skill：给它一段会议、直播或分享的录像，它会

1. 在本地把语音转成带时间戳的文字稿（已有飞书/腾讯会议/Zoom/SRT 文字稿就直接用）；
2. 读完全场，挑出能独立成片的金句、观点、案例、演示、干货，按 A/B/C 打分；
3. 列表给你确认后，用 FFmpeg 精确切片，每条附带对齐好的字幕；
4. 写一份《切片汇总_HANDOFF.md》，之后剪辑每一条时直接拿它开工。

macOS 和 Windows 通用。不需要预装转写软件、ffmpeg 或 Python。视频不会上传到任何地方。

## 安装

### 第 1 步：装 uv（每台电脑一次）

- **macOS**：终端运行 `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Windows**：PowerShell 运行 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

装完重开终端。uv 会替 skill 管理 Python 和所有依赖。

### 第 2 步：装 skill（二选一）

**方式 A：插件（推荐，方便以后更新）**

在 Claude Code 里：
```
/plugin marketplace add shisaq/creator-skills
/plugin install meeting-clipper@creator-skills
```
更新：`/plugin marketplace update creator-skills`

**方式 B：直接复制**

把 `skills/meeting-clipper` 整个文件夹复制到：
- macOS：`~/.claude/skills/meeting-clipper`
- Windows：`C:\Users\<你的用户名>\.claude\skills\meeting-clipper`

然后重启 Claude Code。

## 使用

在 Claude Code 里直接说：

> 帮我把 `D:\录屏\11月产品发布会.mp4` 切成短视频片段

或者 `/meeting-clipper 会议.mp4`。

- 第一次转写会下载约 240MB 的语音模型（国内优先走 ModelScope），之后不再下载。
- 切之前会先给你看选片列表，确认后才开始切。
- 结果在视频旁边的 `切片/` 文件夹：`A_01_xxx.mp4` + 同名 `.srt`、`clip_manifest.csv`、`切片汇总_HANDOFF.md`。

## 技术说明

| 环节 | 方案 | 为什么 |
|---|---|---|
| 依赖管理 | uv + 脚本内联依赖（PEP 723） | 同事不用碰 Python/venv/pip |
| 转写 | sherpa-onnx + SenseVoice（int8）+ Silero VAD | 不依赖 PyTorch，Win/Mac 都有现成安装包；中文准确率高，支持中英混说，自带标点 |
| ffmpeg | 优先用系统里的，没有就用 imageio-ffmpeg 自带的 | 免安装 |
| 编码 | 自动探测硬件编码（VideoToolbox / NVENC / QSV / AMF），失败回退 libx264 | 不用知道自己是什么显卡 |

排障见 [skills/meeting-clipper/references/setup.md](skills/meeting-clipper/references/setup.md)。

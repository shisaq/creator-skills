# 环境准备与排障

脚本只依赖 **uv**。uv 会自动准备 Python、安装依赖（sherpa-onnx、numpy、自带 ffmpeg 的 imageio-ffmpeg），第一次运行稍慢，之后秒开。

## 1. 安装 uv（每台电脑一次）

| 系统 | 命令 |
|---|---|
| macOS | `curl -LsSf https://astral.sh/uv/install.sh \| sh`（或 `brew install uv`） |
| Windows | PowerShell：`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"`（或 `winget install astral-sh.uv`） |

装完**重开终端 / 重启 Claude Code**，让 `uv` 进入 PATH。验证：`uv --version`。

安装命令需要用户自己在终端运行或明确同意后再运行——它会改动用户的系统环境。

## 2. 国内网络加速（下载慢或失败时）

在运行命令前设置环境变量（只影响这一条命令）：

- PyPI 镜像：`UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`
- Python 本体镜像（只有电脑上没有 Python 时 uv 才会去下载）：`UV_PYTHON_INSTALL_MIRROR=https://registry.npmmirror.com/-/binary/python-build-standalone/`

macOS / Git Bash：
```bash
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv run scripts/transcribe.py 会议.mp4
```
PowerShell：
```powershell
$env:UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"; uv run scripts/transcribe.py 会议.mp4
```

转写模型（约 240MB）默认先从 ModelScope 下载，再试 hf-mirror、HuggingFace，国内一般不用额外配置。
在海外的话设置 `MEETING_CLIPPER_REGION=global`，会优先走 HuggingFace / GitHub。

## 3. 没有 uv 也能跑

已有 Python 3.9+ 时：
```bash
python -m pip install sherpa-onnx numpy imageio-ffmpeg
python scripts/clipper.py doctor
```

## 4. 常见问题

| 现象 | 处理 |
|---|---|
| `uv: command not found` | 刚装完没重开终端；或让用户按第 1 节安装。 |
| 依赖下载超时 | 按第 2 节加镜像。 |
| 模型下载全部失败 | 报错里会列出候选地址和目标路径，让用户用浏览器下载后放到对应位置；或设置 `CREATOR_SKILLS_MODELS` 指向已有模型目录。 |
| 切片很慢 | `doctor` 看是否有可用硬件编码器；没有就是 CPU 编码，可加 `--preset ultrafast` 或 `--fast-copy`（极快，但切点会对齐到关键帧，可能差 1–2 秒）。 |
| 硬件编码某条失败 | 脚本会自动改用 CPU 重试这一条，无需处理。 |
| Windows 上中文乱码 | 脚本已强制 UTF-8 输出；manifest CSV 带 BOM，Excel 可直接打开。若文件名乱码，检查是否用的旧版 PowerShell，换 Windows Terminal。 |
| 转写结果语言不对 | 默认 `--language auto`；单语会议指定 `--language zh` 或 `en`。 |
| 想用别的转写工具 | 任何带时间戳的 SRT/VTT/TXT 都可以直接交给 `prepare-transcript`，转写这一步完全可以跳过。 |

## 5. 模型与缓存位置

- 默认：`~/.cache/creator-skills/models`（Windows 为 `C:\Users\<用户名>\.cache\creator-skills\models`），同一套模型被 creator-skills 里的多个插件共用
- 自定义：环境变量 `CREATOR_SKILLS_MODELS`，或 `transcribe.py --model-dir`
- 只下载模型不转写：`uv run scripts/transcribe.py --download-only`

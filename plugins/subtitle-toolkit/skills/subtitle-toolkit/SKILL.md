---
name: subtitle-toolkit
description: 视频字幕工具箱：从视频本地转写出字幕、润色 AI 识别的字幕（修正错别字、同音字、专有名词，时间轴一帧不动）、把字幕翻译成英文等其他语言并保持逐条对齐，还能生成中英双语 ASS 或直接写进 Arctime 工程。支持 SRT/VTT/ASS，macOS 和 Windows 通用，可配合自己的术语表。当用户提到"出字幕""做字幕""加字幕""字幕校对""字幕润色""字幕纠错""修正 SRT""专有名词识别错了""翻译字幕""加英文字幕""出双语字幕""Arctime 双语"，或者给出一个 SRT/ASS 文件、一段剪好的视频要处理字幕时，都应使用本 skill；即使用户只说"这个视频要给海外看""字幕里好多错字"，只要涉及字幕文本的生成、纠错或翻译，也应使用。不适用于：给长视频挑片段切片、往视频画面上烧录特效字幕。
---

# 字幕工具箱

三件事，按用户要的挑着做，也可以串起来：

| 用户要 | 做什么 | 详细步骤 |
|---|---|---|
| 有视频、没字幕 | **转写**出 SRT | 本文「转写」一节 |
| 字幕里有错字 | **润色** | `references/polish.md` |
| 要外语字幕 / 双语 | **翻译** | `references/translate.md` |

常见串法：视频 → 转写 → 润色 → 翻译。翻译前最好先润色，源字幕里的错字会被原样翻过去。

共同原则：**时间轴由脚本管，你只写文本。** 你写出 `序号|文本` 格式的文件，脚本负责按原时间码重组——这样条数、顺序、时间码永远不会被改坏，长字幕也不用整份重写。

## 脚本怎么运行

脚本在本 skill 目录的 `scripts/` 下，用 `uv run` 运行（自动装依赖，Mac 和 Windows 命令一样）：

```bash
uv run "<skill目录>/scripts/transcribe.py" ...
uv run "<skill目录>/scripts/srt_tools.py" ...
```

`srt_tools.py` 没有第三方依赖，也可以直接 `python3` 运行。下文简写成 `transcribe.py` / `srt_tools.py`。

- 没有 `uv`：告诉用户安装方法，**请用户自己运行**（或明确同意后你再运行）——macOS：`curl -LsSf https://astral.sh/uv/install.sh | sh`；Windows（PowerShell）：`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`。装完需要重开终端。
- 国内网络下载依赖慢：命令前加 `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`（PowerShell 写成 `$env:UV_DEFAULT_INDEX="..."; ` 再接命令）。

## 转写

```bash
transcribe.py "<视频或音频>" --max-chars 18
```

- 纯本地运行（sherpa-onnx + SenseVoice），不上传文件，不需要 PyTorch。中英混说用默认的 `--language auto`；确定只有一种语言时指定 `zh` / `en`，更准。
- `--max-chars 18` 让每条字幕短一些，适合直接上屏；不加则默认 28。
- **第一次运行会下载约 240MB 模型**（国内优先走 ModelScope；海外设 `MEETING_CLIPPER_REGION=global`），开始前告诉用户。之后不再下载。
- 速度通常是实时的几十倍。长视频放后台运行，跑完再继续。
- 输出：`<名>_转写.srt`（以及 `.segments.json`）。

转写完的字幕一定会有识别错误，**接着做一遍润色**，除非用户只要个草稿。

用户已经有其他工具出的字幕（剪映、飞书、MacWhisper、YouTube 自动字幕……）就别重新转写，直接润色。

## 术语表

润色和翻译都要先找术语表，它决定专有名词的唯一写法。按这个顺序找，找到第一个就用：

1. 用户在对话里给的路径或直接列出的术语
2. 环境变量 `SUBTITLE_GLOSSARY` 指向的文件
3. 字幕所在目录，以及往上最多三级目录里的 `术语表.md` / `glossary.md`

找到了就告诉用户用的是哪一份。都没有也没关系：用 `references/common_asr_errors.md` 的通用错误表，再结合视频语境判断；做完后在汇报里列出"建议加入术语表"的条目，并提一句可以照 `references/glossary_template.md` 建一份，以后会越来越准。

术语表的格式是三列表格：`误识别 | 中文显示 | 英文显示`。润色用"中文显示"，翻译用"英文显示"。

## 命令速查

| 命令 | 作用 |
|---|---|
| `transcribe.py <媒体> [--max-chars 18] [--language zh]` | 本地转写 → `<名>_转写.srt` |
| `transcribe.py --download-only` | 只预下载模型 |
| `srt_tools.py extract <字幕>` | 打印 `序号|文本`，保存时间码 |
| `srt_tools.py apply <字幕>` | 润色：读 `<字幕>.edits.txt` → `_润色.srt` + 明细 |
| `srt_tools.py build <字幕> --lang en` | 翻译：读 `<字幕>.translations.txt` → `_en.srt` + 校验 |
| `srt_tools.py bilingual <字幕.ass>` | 双语 ASS（独立烧录/上传） |
| `srt_tools.py atpj <字幕.ass>` | 把译文轨写进同名 Arctime 工程 |

## 参考文件

- `references/polish.md` — 润色流程、改与不改的边界、汇报格式。润色前读。
- `references/translate.md` — 翻译流程、字幕化压缩、地道表达、双语成品。翻译前读。
- `references/common_asr_errors.md` — 通用的语音识别高频错误。润色时参考。
- `references/glossary_template.md` — 术语表模板，用户想建自己的术语表时给他。

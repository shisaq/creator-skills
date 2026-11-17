---
name: meeting-clipper
description: 把会议、直播、分享、培训、访谈的录像切成一条条可独立发布或回看的片段：本地转写出带时间戳的文字稿（或直接用已有的 SRT/VTT/飞书/腾讯会议/Zoom 文字记录），读懂内容后挑出金句、观点、案例、演示、干货，按 A/B/C 打分，用户确认后用 FFmpeg 精确切片，并为每条切片生成对齐的字幕和一份交接文档。macOS 和 Windows 通用，不需要预装转写软件或 ffmpeg。当用户给出一个较长的会议/直播/讲座视频，并提到"切片""切条""拆成短视频""剪出精彩片段""挑高光""按议程切开""做会议切片"时使用；即使用户只说"这个直播回放帮我看看能剪出什么""把这场分享拆一拆"，只要是从一段长录像里挑选并切出多个片段，也应使用本 skill。不适用于：给单条已剪好的视频做包装、加字幕特效，或只是转码/压缩视频。
---

# 会议视频切片

把一段长录像变成一批"拿出来就能用"的片段，外加一份让后续剪辑直接上手的交接文档。

整个流程分两半：前一半（转写 → 读稿 → 选片）需要判断力，交给你；后一半（校验 → 切片 → 出字幕 → 记录映射）是确定性的，交给脚本。**选片结果在切之前一定要给用户看一眼**——选哪些、怎么打分是主观的，用户确认比返工便宜得多。

## 脚本怎么运行

脚本在本 skill 目录的 `scripts/` 下。用 `uv run` 运行，它会自动装好依赖（含 ffmpeg），macOS 和 Windows 命令相同：

```bash
uv run "<skill目录>/scripts/clipper.py" <命令> ...
uv run "<skill目录>/scripts/transcribe.py" <视频> ...
```

先跑一次环境检查：

```bash
uv run "<skill目录>/scripts/clipper.py" doctor
```

- 报 `uv` 找不到：读 `references/setup.md`，把对应系统的一行安装命令给用户，**请用户自己运行**（或明确同意后你再运行）。装完需要重开终端。
- 下载依赖慢或超时（常见于国内网络）：按 `references/setup.md` 第 2 节加镜像环境变量后重试。
- 其他报错也先查 `references/setup.md` 的常见问题表。

以下命令里的 `clipper.py` / `transcribe.py` 都指上面这种完整写法。

## 工作流程

### 1. 看输入

- 确认视频存在，记下时长（`doctor` 之后跑 `validate` 时也会打印；也可以先不管）。
- 看用户有没有给文字稿，或视频旁边有没有同名的 `.srt` `.vtt` `.txt` `.md`。
- 问清楚（用户没说的话）用途：默认是**挑能独立发布的短视频片段**（short-video 模式）；如果用户说"按议程切""每个环节一段""内部存档"，用 archive 模式。两种模式的区别见 `references/chapter_schema.md`。

### 2. 拿到带时间戳的文字稿

**有带时间戳的文字稿就别重新转写**——那是浪费用户的时间。按优先级：

1. **用户给的 SRT/VTT/带时间戳的 TXT/MD**（飞书、腾讯会议、Zoom、剪映、MacWhisper 等导出的都行）：
   ```bash
   clipper.py prepare-transcript "<文字稿>"
   ```
   没有时间戳的会议纪要只能当内容参考，切点还得靠转写。

2. **没有文字稿**：本地转写。
   ```bash
   transcribe.py "<视频>" --reading-copy                # 中英混合用默认 auto
   transcribe.py "<视频>" --reading-copy --language zh  # 确定是纯中文/纯英文时指定，更准
   ```
   - 引擎是 sherpa-onnx + SenseVoice，纯本地、不需要 PyTorch、不联网上传视频。
   - **第一次运行要下载约 240MB 模型**，之后不用。开始前告诉用户这一点。
   - 速度通常是实时的几十倍（45 分钟的会大约 1–5 分钟，取决于电脑），长视频用后台运行，跑完再继续，别干等着轮询。

两种方式的产物相同，都在视频（或文字稿）旁边：
- `<名>.srt`：全场字幕，精确时间以它为准
- `<名>.segments.json`：同样内容的结构化版本，切片时用它生成每条切片的字幕
- `<名>_阅读版.md`：约 25 秒一段的阅读版，**选片读这个**——比逐行字幕省很多上下文

### 3. 读稿、选片、写 chapters JSON

先读 `references/chapter_schema.md`，再通读阅读版文字稿（长的话分页读完，别只读开头就下结论）。

读的时候顺手记下三件事，后面交接文档要用：谁在讲（姓名和角色）、整场的结构、识别错的专有名词。

然后写 `<视频名>_chapters.json`（放在视频旁边）：
- 每条片段要能回答"不看前后文，它自己立得住吗"。
- 入出点先从阅读版定大概，再到 SRT 里找具体句子，落在句子边界上。
- A 级克制，一般不超过四分之一。
- 少而精：宁可 12 条好的，也不要 30 条平均的。

### 4. 给用户确认

用一张表列出所有片段：序号、类型、评分、时间、一句话卖点。再附上：一共几条、A/B/C 各几条、哪些段落被刻意跳过了（比如开场等人、二维码环节）。

问用户：直接全部切，还是只切 A/B，或者要调整哪些。用户确认前不要切。

### 5. 校验并切片

```bash
clipper.py validate --chapters "<chapters.json>" --video "<视频>"
clipper.py split "<视频>" --chapters "<chapters.json>" --transcript "<名>.segments.json" --output-dir "<视频所在目录>/切片"
```

- `validate` 报 ERROR 就改 JSON 再来；重叠只是 WARN，archive 模式或用户要求时可以忽略。
- `split` 默认：前加 2 秒、后加 5 秒余量（`--pad-start` / `--pad-end`），`--encoder auto` 自动选硬件编码（Mac 用 VideoToolbox，Windows 依次试 NVIDIA/Intel/AMD，都没有就用 CPU），某条硬件编码失败会自动用 CPU 重试。
- 传了 `--transcript`，每条切片旁边会生成同名 `.srt`，时间已对齐到切片本身。
- 只切部分：`--scores A,B`。要粗剪预览可以加 `--fast-copy`（极快，但切点对齐关键帧，可能偏 1–2 秒）。
- 切 20 条左右通常几分钟，用后台运行。

切完检查输出里的 `Finished: x/y`，有失败的条目要告诉用户。

### 6. 写交接文档

在切片目录写 `切片汇总_HANDOFF.md`，按 `references/handoff_template.md` 的结构。这一步由你来写，不是脚本——背景、结构、术语订正都来自你读稿时的理解。

它的读者是**之后的会话或剪辑同事**：拿着这一个文件就能开始加工某一条切片。所以：
- 文件名、时间、卖点从 `clip_manifest.csv` 和 chapters JSON 里取，别凭记忆写。
- 术语订正只写确定的；拿不准的人名、数字放"待核实"。
- 开剪建议里如果当前环境有字幕润色、短视频包装之类的 skill，可以点名推荐；没有就只写通用建议。

最后告诉用户：切了几条、放在哪、交接文档写好了，可以每条开一个新会话指向这份文件继续加工。中间产物（转写字幕、阅读版、chapters JSON）都在视频旁边，用户不需要可以自行删除。

## 命令速查

| 命令 | 作用 |
|---|---|
| `clipper.py doctor` | 检查 ffmpeg、可用编码器、模型是否已下载 |
| `clipper.py prepare-transcript <稿>` | 解析已有文字稿，生成 srt / segments.json / 阅读版 |
| `transcribe.py <视频> --reading-copy [--language zh]` | 本地转写，产物同上 |
| `transcribe.py --download-only` | 只预下载模型 |
| `clipper.py validate --chapters <j> --video <v>` | 切前校验 |
| `clipper.py split <v> --chapters <j> --transcript <seg> [--scores A,B] [--output-dir d]` | 切片 + 每条字幕 + manifest |

## 参考文件

- `references/chapter_schema.md` — chapters JSON 字段、两种模式、类型和评分标准、找准入出点的方法。写 JSON 前读。
- `references/handoff_template.md` — 交接文档结构。写 HANDOFF 前读。
- `references/setup.md` — 安装 uv、国内镜像、常见报错。环境出问题时读。

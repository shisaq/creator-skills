---
name: selfmedia-video
description: 口播自媒体视频生产线：把一段手机自拍/口播原片做成可发布的竖屏短视频——逐字转写 → 删句方案 → 链接原素材的 FCPXML 粗剪 → (用户在 Final Cut 精修) → HyperFrames 包装（人脸追踪的画中画、真实信源按原样式翻成中文的卡片、字幕避开嘴巴、关键词高亮、BGM 与音效、结尾互动卡）→ 发布文案 + 3:4 封面。当用户给出一段口播/自拍/vlog 原片说"做成自媒体视频""帮我剪一下再包装""这条口播要发视频号/抖音""出个粗剪""做包装""加字幕和特效""做个封面"，或者丢来一个已经剪好的口播成片要包装时，都应使用本 skill；即使只说"这段视频帮我弄一下发出去"，只要素材是单人口播，也应触发。不适用于：会议/直播长录像切片（meeting-clipper）、只要字幕文件（subtitle-toolkit）、只写口播稿或文案（short-video-writer）、无真人出镜的纯动画视频。
---

# 口播自媒体视频

一条口播原片走完五步变成能发的视频。脚本做重活，你做三件只有人能判断的事：**删哪句、怎么包装、文案怎么写**，并且只在三个地方停下来等用户。

```
原片 ─①转写+人脸─②★删句方案─③★FCPXML粗剪─(用户FCPX精修)─④★包装成片─⑤文案+封面
```

用户给的是**已经剪好的成片**时，跳过②③，直接从④开始（④里会对成片重新转写和追踪人脸）。

脚本都在本 skill 的 `scripts/` 下，下面写作 `scripts/…`。Python 脚本带内联依赖，用 `uv run` 跑（`captions.py` `build.py` `hf.py` `cover.py` `fetch_post.py` 只用标准库，`python3` 也行）。环境和排障见 `references/setup.md`。

## 0 · 开工前：出镜档案

先找这个人的**出镜档案**（谁、什么口吻、配色、BGM 去哪找、哪些规矩），按顺序找到第一个就用：

1. 用户在对话里给的路径或描述
2. 环境变量 `SELFMEDIA_PROFILE` 指向的文件
3. `~/.config/creator-skills/profiles/` 下名字对得上的 `*.md`
4. 素材目录及往上三级的 `出镜档案.md`

没有就问一句"这是谁的账号、文案用第一人称还是介绍他"，然后照 `references/profile_template.md` 帮他建一份，放到 `~/.config/creator-skills/profiles/`。档案是用户的私人数据，**不要写进本仓库**。

## ① 转写 + 人脸追踪（自动，两条并行）

```bash
uv run scripts/words.py <原片> --terms "专名1,专名2"      # → <stem>.words.json + <stem>.transcript.md
uv run scripts/face.py  <原片>                              # → <stem>.face.json
```

- `--terms` 填这条视频里会出现的人名、公司名、产品名，识别准确率差别很大。
- 设置了 `SELFMEDIA_FUNASR_URL`（自建的 FunASR 字幕工作台）就优先用它，中文更准、带专名热词；没设或连不上自动退到本机 SenseVoice。
- 读一遍 `transcript.md`。这是你理解视频和写删句方案的依据。

## ② ★ 删句方案（停下来给用户看）

口播拖沓几乎都来自**内容**，不是停顿：同一个意思讲了两遍、"那当然有一些有趣的点"这种过渡套话、结尾"这是我的一些思考，分享给大家"式总结、开头"今天在…正好想到"式铺垫。按这个顺序找：

1. **开头**：第一句话能不能直接是钩子？铺垫句删掉，让第一句话对上标题。
2. **重复**：同一个判断说了两次的，留更好的那次。
3. **过渡套话**：删掉后由包装里的字卡接上（"彩蛋①"这种）。
4. **结尾**：停在最有力的那句话上，后面的总结交给结尾互动卡。
5. **口头语**：`嗯/呃` 单独成词的可以删（用 `near` 指定是哪一个）。

写成一份《剪辑与包装方案.md》给用户，同时包含：删句表（原片时间、原话、理由、预计省几秒）、3–5 个标题候选（标出推荐）、开头钩子、分段包装设想（哪几段缩成小窗配什么卡、要找哪些真实信源）、预计成片时长。**删句会改变意思的地方要标出来**，让用户拍板。

用户确认后写 `cutplan.json`（格式见 `scripts/roughcut.py` 开头）：**用原话指定删什么**，不用自己估时间码——脚本在逐字时间轴上找到这段话，并把刀口落在前后停顿最安静的那一帧。

## ③ ★ FCPXML 粗剪（交给用户精修）

```bash
uv run scripts/roughcut.py <原片> <stem>.words.json cutplan.json [--preview]
```

产出 `<stem>_粗剪.fcpxml`（链接原素材、可在 FCPX 里拖回删掉的内容；每个删句接缝打了标记）、`_剪辑点.md`，`--preview` 再出一个快速预览 mp4。句间超过 0.3s 的停顿收到 0.15s。

**粗剪不加任何缩放**——每个跳切都放大缩小会很晃，用户明确不要。告诉用户：在 FCPX 精修后导出成片（SDR Rec.709）放回同目录，回来说一声。脚本报"找不到"的删句，说明原话写得和转写不一致，改了再跑。

## ④ ★ 包装成片

**4a 准备**（对精修成片）：
```bash
uv run scripts/words.py <成片> --terms "…"
uv run scripts/face.py  <成片>
python3 scripts/captions.py draft <成片>.words.json --max 12 --terms "专名…" > phrases.txt
```
改 `phrases.txt`：修识别错（专名、同音字、"刺杀"这类不准确的词）、数字写成阿拉伯数字、一行一组。然后
```bash
python3 scripts/captions.py align <成片>.words.json phrases.txt --out captions.json --srt <成片>_字幕.srt
```

**4b 找真实信源**——比任何画出来的图都有说服力，见 `references/sources.md`：
- 新闻报道 → 取标题原文，翻成中文，用 `news` 卡按原媒体的版式和颜色重做。
- X 帖子 → `python3 scripts/fetch_post.py <链接> --out img/` 拿全文和头像，翻译后用 `post` 卡重做。
- 人物照片 → Wikimedia Commons 的 CC 授权图，结尾卡写署名。
- **外文素材一律翻成中文、按原样式重做，不要放英文原图配中文字幕。** 卡片旁用小字标"中文译文"。
- 引用前核实：谁在什么场合说的（演讲还是发帖）、日期、原话。

**4c 写包装规格 `spec.json`**，格式和每种卡片见 `references/spec.md`。版式规矩（全部来自真实返工，见 `references/rules.md`）：
- 全屏段落**只有人和字幕**。顶部文字条会和字幕、人脸抢注意力；全屏段只留开头钩子标题和结尾一句大字。
- 信息密集的段落（引语、数字揭晓、对比、时间轴）把人缩进右上角小窗，卡片占画面。小窗自动跟着脸走。
- 一张卡 4–12 秒；卡片元素跟口播同步出现（`at` 填说到那个词的时间，从 `words.json` 查）。
- 强调只用一次推近（`punch`），不要来回缩放。

**4d 生成、检查、看图**：
```bash
python3 scripts/build.py spec.json                     # → 包装/（HyperFrames 工程）
python3 scripts/hf.py check 包装
python3 scripts/hf.py snap  包装 2,8,13,20,40,47,61,80,94,99
```
一定要**看截图**再交：字幕有没有压到嘴、小窗里脸是否居中、卡片和字幕有没有叠、转场瞬间有没有残影。有问题改 spec 重跑 build（build 会清掉旧的 compositions 再生成）。

**4e 渲染**：
```bash
python3 scripts/hf.py render 包装 <成片名>_包装_v1.mp4
```
交付时说清：包装了什么、用了哪些真实信源（附链接）、字幕改了哪些识别错、哪些事实需要用户再确认。用户逐条反馈后改 spec 出 v2，不要从头重来。

## ⑤ 发布文案 + 封面

- **文案**：如果装了 `short-video-writer`，按它的 `references/publish.md` 写，并把出镜档案路径作为账号档案传给它；没装就按出镜档案的口吻写视频号/抖音/YouTube（中英），**不编造**素材里没有的数字。个人号默认第一人称、弱化头衔（以档案为准）。
- **封面**：在 spec 里加 `cover` 块（挑一帧笑着、睁眼的画面——先看 contact sheet），然后
  ```bash
  python3 scripts/cover.py spec.json        # → 封面_3x4.png（1080×1440）
  ```

## 交付物（都在素材目录）

`<stem>_粗剪.fcpxml` · `剪辑与包装方案.md` · `包装/`（可再编辑的工程）· `<成片>_包装_vN.mp4` · `<成片>_字幕.srt` · `封面_3x4.png` · `社交平台文案.md`

## Codex / 其他 agent

本 skill 不依赖 Claude 专属工具：所有重活在脚本里，命令行能跑就行。需要"看图"的步骤（检查截图、挑封面帧），没有看图能力时把图片路径交给用户确认。

# selfmedia-video

把一段手机自拍口播原片，做成能直接发视频号 / 抖音 / YouTube Shorts 的竖屏短视频：

1. **逐字转写 + 人脸追踪**：每个字都有时间；每 0.2 秒记一次脸在哪。
2. **删句方案**：找出重复、过渡套话、拖沓的开头结尾，连同标题候选和包装设想一起给你确认。
3. **FCPXML 粗剪**：按原话删句（刀口落在停顿最安静处），收紧停顿，链接原素材，导入 Final Cut Pro 精修。
4. **包装成片**：HyperFrames 渲染。
   - 开头钩子标题、结尾互动卡。
   - 信息密集的段落把人缩进右上角小窗，小窗跟着脸走。
   - 真实信源（新闻标题、X 帖子）按原样式翻成中文重做；人物照片用 CC 授权图并自动署名。
   - 字幕放在下巴以下、关键词高亮；BGM 和音效。
5. **发布文案 + 3:4 封面**。

只在三处停下来等你：删句方案、粗剪精修、成片审看。给它一条已经剪好的口播，就直接从第 4 步开始。

## 安装

先装 [uv](https://docs.astral.sh/uv/) 和 Node.js 18+（HyperFrames 首次使用时由 `npx` 自动下载），以及 ffmpeg。

```
/plugin marketplace add shisaq/creator-skills
/plugin install selfmedia-video@creator-skills
```

或者把 `skills/selfmedia-video` 复制到 `~/.claude/skills/`（Codex：`~/.codex/skills/`）。

## 用法

> 帮我把 `~/Movies/口播0312.mov` 做成一条自媒体视频

> 这条已经剪好了，帮我包装一下，再出个封面和发布文案

建议先建一份**出镜档案**（口吻、配色、BGM 目录、常用专名），放在 `~/.config/creator-skills/profiles/`，模板见 [references/profile_template.md](skills/selfmedia-video/references/profile_template.md)。

## 转写后端

默认本机 SenseVoice（离线，模型约 240MB，与 meeting-clipper、subtitle-toolkit 共用）。有自建 FunASR 字幕服务的，设 `SELFMEDIA_FUNASR_URL` 即可优先使用，不可用时自动回退。详见 [references/setup.md](skills/selfmedia-video/references/setup.md)。

## 设计

- 脚本管时间轴，模型管判断：删句用原话指定、字幕先写字再对时间，时间码不靠模型估。
- 包装由一个 `spec.json` 描述（卡片类型：新闻、帖子、两人对照揭晓、对比行、时间轴、截图），改一行重新生成，不用改代码。见 [references/spec.md](skills/selfmedia-video/references/spec.md)。
- 版式规矩来自真实返工，写在 [references/rules.md](skills/selfmedia-video/references/rules.md)：字幕不压嘴、小窗跟脸、全屏段不叠文字条、不来回缩放、外文信源翻译重做。

# 环境与排障

## 需要什么

| 工具 | 用途 | 安装 |
|---|---|---|
| uv | 跑带内联依赖的 Python 脚本（转写、人脸、粗剪） | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js 18+ | HyperFrames 渲染（`npx hyperframes`，首次使用自动下载，不用单独装） | nodejs.org 或 `brew install node` |
| ffmpeg / ffprobe | 解码、预览、合成音效 | `brew install ffmpeg` / `winget install ffmpeg` |
| Google Chrome | 封面截图；HyperFrames 首次渲染会自己下载无头浏览器 | — |
| Final Cut Pro（可选） | 精修粗剪；没有 FCPX 就用 `roughcut.py --preview` 的成片直接进包装 | — |

第一次跑会下载：SenseVoice 模型约 240MB（与 meeting-clipper、subtitle-toolkit 共用 `~/.cache/creator-skills/models`）、OpenCV、HyperFrames CLI 和无头浏览器。

## 转写后端

- 默认：本机 sherpa-onnx + SenseVoice，离线，中英混说都行。
- 自建 FunASR 字幕工作台：`export SELFMEDIA_FUNASR_URL=https://<你的服务>`。服务需要提供
  `PUT /api/upload`、`GET /api/projects/<id>`、`GET /api/projects/<id>/tokens`（逐字 `{t, s, e, p, gap}`，毫秒）。
  连不上会自动退回本机。

## 常见问题

- **渲染卡在 "Checking browser..."**：`hf.py render` 已自动绕过（把已下载的 chrome-headless-shell 传给 `HYPERFRAMES_BROWSER_PATH`）。还卡就手动 `export HYPERFRAMES_BROWSER_PATH=<无头浏览器路径>`。
- **face.py 报 `CascadeClassifier`**：OpenCV 5 去掉了它，脚本已锁 `<5`；手动装过 5.x 时用 `uv run` 跑就行。
- **roughcut 报"找不到删句"**：cutplan 里的原话要和 `transcript.md` 的写法一致（标点无所谓）；短词（嗯、呃）加 `near` 秒数。
- **字幕某行时间不准**：align 会列出匹配差的行（常见于数字：ASR 写"一九六三"，字幕写"1963"），这些行按前后行插值；预览里看一眼。
- **素材是 HDR（iPhone 杜比视界/HLG）**：粗剪 FCPXML 会正确标注 HLG；包装前请从 FCPX 导出 SDR Rec.709 成片。
- **成片卡顿/冻帧**：build 已把成片转成每秒一个关键帧；直接改了 `包装/assets/talk.mp4` 的话要保持 `-g 30`。

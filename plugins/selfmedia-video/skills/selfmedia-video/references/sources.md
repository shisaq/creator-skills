# 找真实信源

口播里提到的新闻、原话、人物、日期，能用真实材料就不要画示意图。顺序：先核实事实，再取材料，最后翻译重做。

## 1. 核实

- 搜原始报道（中英文各搜一次），确认：谁、在什么场合说的（现场发言 / 自己发帖 / 别人转述）、日期、原话。
- 口播里的说法和事实有出入时（"离开两年"实际 17 个月、"刺杀"实为"遇害"），字幕改准确，口播不动；时间轴/卡片写准确日期，并在交付时告诉用户。

## 2. 新闻标题 → news 卡

- 用无头浏览器截原文页面（只为取版式、颜色、logo）：
  ```bash
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars \
    --force-device-scale-factor=2 --window-size=600,1000 --virtual-time-budget=20000 \
    --screenshot=page.png "<文章链接>"
  ```
- 从截图裁 logo（`ffmpeg -i page.png -vf crop=w:h:x:y logo.png`），取主色和顶栏色（`ffmpeg ... -vf crop=4:4:x:y -f rawvideo -pix_fmt rgb24 - | xxd -p`）。
- 标题、作者、时间翻成中文填进 news 卡。

## 3. X 帖子 → post 卡

```bash
python3 scripts/fetch_post.py https://x.com/<user>/status/<id> --out img/
```
拿到全文（含"显示更多"折叠部分）、作者、时间、点赞数、头像。逐段完整翻译，`$NVDA` 这类 cashtag 保留原文。头像是方形的账号（机构号）设 `"avatar_radius": "8px"`。

想要一张英文原帖的图做对照（一般不需要）：X 官方嵌入页可以直接截，`https://platform.twitter.com/embed/Tweet.html?id=<id>&theme=light`。

## 4. 人物照片 → Wikimedia Commons

```bash
curl -s -A "creator-skills/1.0" "https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrlimit=8&gsrsearch=<人名>&prop=imageinfo&iiprop=url|size|extmetadata&format=json"
```
挑 `LicenseShortName` 为 CC BY / CC BY-SA / Public domain 的、脸清楚的；记下作者和协议，写进 cta 的 `credits`。不用新闻图库（Getty 等）的照片。

## 5. 别做的

- 不编造帖子、不改原话、不"润色"引语让它更有冲击力。
- 不用真人照片做成看起来像真人说了某句话的图（引语要标出处）。
- 不把英文原图放上去配中文字幕。

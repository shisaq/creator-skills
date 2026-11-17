# 字幕翻译

目标：译文能在字幕停留的时间里读完，意思准，读起来像母语者写的字幕。默认中译英；其他语言对同样适用。

## 流程

1. **抽取**
   ```bash
   srt_tools.py extract "<字幕>"
   ```

2. **通读全文再动笔。** 确定语域：产品演示、观点分享、课程、访谈、客户案例，语气各不相同。

3. **加载术语表**（见 SKILL.md）。术语表里的"英文显示"一列就是唯一译名，照抄。

4. **写译文**到 `<字幕文件名>.translations.txt`，**每条一行，一条都不能少**：
   ```
   1|Today we're looking at a new feature.
   2|It turns a screen recording into a requirements doc.
   ```
   一条原文对应一条译文，不合并、不拆分——时间轴不能动。

5. **生成并校验**
   ```bash
   srt_tools.py build "<字幕>" --lang en
   ```
   脚本检查条数是否对齐、有没有残留中文、阅读速度是否超标（英文默认 20 字符/秒）。
   **每条超速警告都要回去压缩那条译文**，再 build，直到没有警告，或者你确认那条压不下去了（写进汇报）。

6. **双语成品**（只在输入是 `.ass` 时做）：
   - 同目录有同名 `.atpj`（Arctime 工程）：`srt_tools.py atpj "<字幕.ass>"`，生成 `-双语.atpj`，用 Arctime 打开就能出片。
   - 只是要烧录或上传：`srt_tools.py bilingual "<字幕.ass>"`，生成 `-双语.ass`。
   - 译文字体默认 Arial（Win/Mac 都有），用户有偏好就加 `--l2-font "字体名"`，或设置环境变量 `SUBTITLE_L2_FONT`。

   为什么 Arctime 要用 `atpj` 而不是导入双语 ASS：Arctime 的工程以 `.atpj` 为准，导入 ASS 时不会还原分组和样式，所有行会挤进同一组、套同一个样式，中英文还会叠成两份。`atpj` 命令直接把译文写进工程的第 2 组。

## 字幕化压缩

字幕不是文档，**读得完比信息全更重要**。

- 口语填充直接省："那""就是说""其实""对吧""我们可以看到"。
- 短词换长词：utilize → use，in order to → to，is able to → can。
- 中文常在半句处断条。先按整句意思翻，再把英文按"这一刻画面和声音在说什么"分回各条，保证每条大致同步、连起来读通顺。
- 英文带完整标点：跨条的句子用逗号、冒号衔接，句末用句号或问号。
- 可以舍弃修饰，不能舍弃事实、数字和转折。

## 地道表达

避免翻译腔。常见的中文商务/科技说法：

| 中文 | 地道英文 | 避免 |
|---|---|---|
| 降本增效 | cut costs and boost efficiency | reduce cost and increase effect |
| 落地 | deploy / put into production | land |
| 赋能 | enable / help (someone) do | energize |
| 打通 | connect / integrate | break through |
| 闭环 | close the loop / end-to-end | closed ring |
| 抓手 | lever / starting point | grip |
| 私有化部署 | on-premises deployment | privatized deployment |
| 开箱即用 | out of the box | open box use |
| 智能体 | AI agent | intelligent body |
| 干货 | practical takeaways | dry goods |
| 痛点 | pain point | painful point |
| 复盘 | retrospective / look back at | resume the game |

语气跟着语域走：演示用平实的祈使句（"Click here to…"），观点分享可以有力一些（短句、主动语态），客户案例保持商务口吻。

人名用拼音（姓在前，如 Wang Xiaoming），讲话人有英文名就用英文名。公司名、产品名照官方写法，不意译。

## 汇报格式

```
## 翻译完成

**输出**：<名>_en.srt；<名>-双语.atpj（Arctime 出片用）；<名>-双语.ass（独立烧录用）
**条数**：N 条，时间轴与原文逐条对齐
**专名译法**：本片涉及的人名、产品名、术语及采用的译法
**压缩说明**：明显精简过的条目、舍弃了什么（没有就省略）
**遗留警告**：压不到阅读速度线以下的条目及原因（没有就省略）
```

用 Arctime 出片时提醒用户打开 `-双语.atpj`，不要导入 `-双语.ass`。中间文件（`.cues.json`、`.translations.txt`）留着方便返工，确认成品后可以删。

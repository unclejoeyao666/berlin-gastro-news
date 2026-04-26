# Berlin Gastro News — 每日工作流

> 由本地 OpenClaw 在 Europe/Berlin 06:00 触发；总耗时约 5-15 分钟（视新闻条数和翻译长度）。

## 7 步流水线

```
1. 抓取 RSS    → 入 SQLite
2. 选篇 Top10  → daily-selected.json
3. AI 翻译     → 写回 DB（translated_*）+ 生成 audio_script.md
4. 渲染文章    → site/src/content/articles/*.md
5. 渲染简报    → site/src/content/briefings/<date>.md + daily/<date>/{briefing.md, meta.json}
6. 合成音频    → daily/<date>/audio.mp3 + site/public/audio/<date>.mp3
7. 推送        → git pull/add/commit/push → GH Action 自动部署
```

## 完整命令序列

```bash
cd /Users/unclejoe/Media_Workspace/berlin-gastro-news

# 1. 抓取
python3 scripts/harvest.py

# 2. 选篇
python3 scripts/select_top.py --count 10

# 3. AI 翻译（OpenClaw 在自己的会话内做的认知工作；不调外部 API）
#   - 读 daily-selected.json 的每条
#   - WebFetch 原文（必要时；正文 < 500 字符或付费墙时降级）
#   - 翻译标题/全文/摘要 + 写影响分析 + 选 1-3 个 industry_tags
#   - 用以下伪代码写回 DB：
#     UPDATE news_articles
#     SET translated_title=?, translated_summary=?, translated_body=?,
#         impact_analysis=?, industry_tags=?  -- JSON array of valid slugs
#     WHERE id=?
#   - 生成 daily/<YYYY>/<YYYY-MM>/<DATE>/audio_script.md（朗读串稿，结构见下）

# 4. 渲染文章
python3 scripts/publish_article.py --all-pending

# 5. 渲染简报
python3 scripts/publish_briefing.py --date today

# 6. 音频合成
python3 scripts/render_audio.py --date today

# 7. 推送
python3 scripts/git_publish.py --date today
```

## 标签规则（步骤 3 必须遵守）

合法标签 slug：

| slug | 中文 |
|---|---|
| `gastro-law` | 餐饮法规 |
| `tax-finance` | 财税·补贴 |
| `labor-staffing` | 招工·人力 |
| `energy-cost` | 能源·成本 |
| `supply-food` | 食材·供应链 |
| `hygiene-safety` | 卫生·食品安全 |
| `digital-tech` | 数字化·AI |
| `real-estate` | 场地·租赁 |
| `events-marketing` | 活动·营销 |
| `trends-consumer` | 消费趋势 |
| `geopolitics-trade` | 国际·贸易 |
| `berlin-local` | 柏林本地 |

每篇必须 1-3 个标签，写到 `news_articles.industry_tags` 字段（JSON 数组）。

## audio_script.md 模板

```markdown
早上好，欢迎收听柏林餐饮商业新闻简报。今天是 YYYY 年 MM 月 DD 日，星期X。

今天为您播报 10 条值得关注的新闻。

第一条。<中译标题>。
<重点 + 影响分析浓缩，约 30-60 秒>。

第二条。<中译标题>。
<...>

[第 3-10 条]

以上就是今天的简报。详情请访问网站 unclejoeyao666 点 github 点 io 斜杠 berlin-gastro-news。
祝您生意兴隆，明天见。
```

要点：
- 总长度目标 8-12 分钟（约 1500-2500 中文字符）
- 不要写 Markdown 标题（render_audio.py 会 strip）
- 不要嵌入 URL（TTS 会读出 https）
- 数字与日期写汉字（TTS 更自然）

## DB 写入 SQL 范例（步骤 3 用）

```python
import json, sqlite3
conn = sqlite3.connect('data/news.db')
conn.execute("""
    UPDATE news_articles
       SET translated_title = ?,
           translated_summary = ?,
           translated_body = ?,
           impact_analysis = ?,
           industry_tags = ?,
           slug = ?
     WHERE id = ?
""", (
    "中译标题",
    "中文摘要（≤160 字符）",
    "中文全文 Markdown",
    "对柏林餐饮业的影响分析 Markdown",
    json.dumps(["gastro-law", "berlin-local"], ensure_ascii=False),
    "english-keyword-slug-2026-04-26",  # 可空，publish_article.py 会自动生成
    article_id,
))
conn.commit()
conn.close()
```

或更简单地用 `scripts/lib/news_db.py` 的 `update_translation()` 方法：

```python
from scripts.lib.news_db import NewsDB
with NewsDB('data/news.db') as db:
    db.update_translation(
        article_id=row['id'],
        translated_title="...",
        translated_summary="...",
        translated_body="...",
        impact_analysis="...",
        industry_tags=["gastro-law"],
        slug="...",
    )
```

## Discord 投递（OpenClaw 的另一个 cron）

读 `daily/<YYYY>/<YYYY-MM>/<DATE>/`：
- `briefing.md` — Markdown 文字简报（含网页链接）
- `audio.mp3` — 附件
- `meta.json` — 解析 `article_slugs` / `briefing_url` / `audio_url` 用

## 失败重入

任何步骤失败：
1. 修复问题
2. 从失败步骤往后重跑（脚本都是 `--date YYYY-MM-DD` 幂等）
3. 重跑步骤 7（git_publish）会先 `git pull --rebase`

如 GH Action build 失败：检查 `cd site && npm run build` 本地能否 build；多半是 frontmatter schema 校验。

## 监测

- DB 健康：`python3 -m scripts.lib.news_db data/news.db --stats`
- 站点状态：`curl -sI https://unclejoeyao666.github.io/berlin-gastro-news/`
- 最近 5 期 broadcast_log：
  ```bash
  sqlite3 data/news.db "SELECT broadcast_date, article_count FROM broadcast_log ORDER BY broadcast_date DESC LIMIT 5;"
  ```
- 最近 GH Action 运行：`gh run list --limit 5`

## 文件路径速查

| 路径 | 用途 |
|---|---|
| `data/news.db` | 主 SQLite 库（进版本控制） |
| `data/sources.json` | RSS 源清单 |
| `daily/<Y>/<Y-M>/<DATE>/briefing.md` | Discord 文字简报 |
| `daily/<Y>/<Y-M>/<DATE>/audio.mp3` | TTS 成品 |
| `daily/<Y>/<Y-M>/<DATE>/audio_script.md` | TTS 源稿 |
| `daily/<Y>/<Y-M>/<DATE>/meta.json` | 元信息（slug 列表 / URL） |
| `site/src/content/articles/<slug>.md` | 文章详情页 |
| `site/src/content/briefings/<DATE>.md` | 简报集合页 |
| `site/public/audio/<DATE>.mp3` | 站内音频镜像（可直链） |
| `daily-selected.json` | 步骤 2-3 中间态（gitignored） |

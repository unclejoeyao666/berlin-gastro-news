# Berlin Gastro News v2 — 设计文档

**作者**：Claude (Opus 4.7) + unclejoe
**日期**：2026-04-26
**状态**：已批准，进入实现阶段
**仓库**：`unclejoeyao666/berlin-gastro-news`（待创建）
**部署**：GitHub Pages → `https://unclejoeyao666.github.io/berlin-gastro-news/`

---

## 1. 范围与非范围

### 范围（本项目交付）
- 每日 RSS 抓取 + 去重 + 选篇（10 条/天）
- 每条入选新闻：中文全文翻译 + 对柏林餐饮业的影响分析 + 行业标签 + 原文参考
- 静态网站（Astro）+ GitHub Pages 自动部署
- 每日 TTS 中文音频
- 标准化的"成品文件包"路径，供下游 OpenClaw 取走

### 非范围（OpenClaw 负责）
- cron 调度
- Discord 推送
- 翻译 / 影响分析 / 标签选择的认知工作 — 由 OpenClaw 会话内的 Claude 直接完成，不调用外部 LLM API

### 设计约束
- 沿用 `unclejoeyao666/cashcow-seo-site` 已经跑通的 Astro + GH Pages 模式
- 沿用 `Media_Workspace/ai-daily-news` 已经跑通的 SQLite + bloom + FTS5 数据层
- 直接复用 `/Users/unclejoe/Doc_Workspace/scripts/minimax_tts.py`（双引擎 TTS，已生产验证）

---

## 2. 仓库与目录结构

单仓库，public：

```
berlin-gastro-news/
├── .github/workflows/deploy.yml      # push main → Astro build → GH Pages
├── data/
│   ├── news.db                       # SQLite（FTS5 + bloom 查重）
│   └── sources.json                  # RSS 订阅源
├── scripts/                           # 确定性 Python 脚本（OpenClaw 调用）
│   ├── harvest.py                    # 抓 RSS → 入 DB
│   ├── select.py                     # 选当日 Top10 → daily-selected.json
│   ├── publish_article.py            # 写 1 篇 Astro 文章
│   ├── publish_briefing.py           # 写当日 briefing 索引 + audio_script + meta
│   ├── render_audio.py               # 包装 minimax_tts.py
│   ├── git_publish.py                # add/commit/push 一站式
│   ├── migrate_v1_to_sqlite.py       # 一次性数据迁移
│   └── lib/
│       ├── news_db.py                # SQLite ORM（移植 ai-daily-news）
│       └── normalize.py              # URL 归一化（移植 ai-daily-news）
├── site/                              # Astro 项目
│   ├── astro.config.mjs              # site + base 配置
│   ├── package.json
│   ├── src/
│   │   ├── content.config.ts         # collections: articles, briefings
│   │   ├── content/
│   │   │   ├── articles/             # 单篇翻译版（slug.md）
│   │   │   └── briefings/            # 当日简报（YYYY-MM-DD.md）
│   │   ├── pages/
│   │   │   ├── index.astro
│   │   │   ├── briefings/[...slug].astro
│   │   │   ├── articles/[...slug].astro
│   │   │   ├── tags/[tag].astro
│   │   │   ├── archive.astro
│   │   │   ├── about.astro
│   │   │   └── rss.xml.js
│   │   ├── layouts/
│   │   │   ├── BaseLayout.astro
│   │   │   ├── ArticleLayout.astro
│   │   │   └── BriefingLayout.astro
│   │   └── components/
│   │       ├── ArticleCard.astro
│   │       ├── TagBadge.astro
│   │       └── AudioPlayer.astro
│   └── public/
│       └── audio/<YYYY-MM-DD>.mp3
├── daily/                             # OpenClaw 取件区（每日成品包）
│   └── <YYYY>/<YYYY-MM>/<YYYY-MM-DD>/
│       ├── briefing.md               # Discord 文字简报
│       ├── audio_script.md           # TTS 源稿
│       ├── audio.mp3                 # 成品音频
│       └── meta.json                 # 元信息
├── workflows/
│   └── DAILY_WORKFLOW.md             # OpenClaw 每日流程文档
├── docs/
│   └── superpowers/specs/            # 本设计文档所在
├── archive/
│   └── v1/                           # v1 时期的历史代码与数据
├── README.md
└── .gitignore
```

### .gitignore 要点
- `data/news.db-shm`, `data/news.db-wal`（SQLite WAL）
- `site/node_modules/`, `site/dist/`, `site/.astro/`
- `daily-selected.json`（中间态）

`data/news.db` 本身**进版本控制**，方便 OpenClaw 在不同机器上接续运行。

---

## 3. 数据层（SQLite）

### 3.1 schema（基于 ai-daily-news 扩展）

```sql
-- 沿用 ai-daily-news 的 sources / news_articles / news_fts / broadcast_log 四张表，
-- 在 news_articles 上增加以下字段：
ALTER TABLE news_articles ADD COLUMN translated_title TEXT;
ALTER TABLE news_articles ADD COLUMN translated_summary TEXT;
ALTER TABLE news_articles ADD COLUMN translated_body TEXT;
ALTER TABLE news_articles ADD COLUMN impact_analysis TEXT;
ALTER TABLE news_articles ADD COLUMN industry_tags TEXT;   -- JSON array
ALTER TABLE news_articles ADD COLUMN slug TEXT;            -- 唯一，Astro 文章路径
ALTER TABLE news_articles ADD COLUMN published_briefing_date TEXT;

CREATE UNIQUE INDEX idx_articles_slug ON news_articles(slug)
  WHERE slug IS NOT NULL;
```

### 3.2 复用机制
- **bloom filter**（`db/news_db.py` 中的 `BloomFilter`）：内存预检，<1ms
- **FTS5**：title + content 全文搜索（管理用）
- **URL 归一化**：去 utm/fbclid 等 tracking 参数后做跨源查重
- **复合索引** `idx_articles_unplayed_queue` 消除 ORDER BY 的 filesort

### 3.3 数据迁移（一次性）
`scripts/migrate_v1_to_sqlite.py`：
- 读 `archive/v1/news-db.json`
- 每条 → `add_article()`
- `presented=true` 的标 `broadcast_status='played'`，`presented_at` → `broadcast_date`
- 旧 `categories` 灌进 `topic_tags`
- `industry_tags` 留 NULL（v2 不回填翻译）

---

## 4. 行业标签体系

固定 12 个标签，中文显示，slug 用 kebab-case：

| slug | 中文 | 说明 |
|---|---|---|
| `gastro-law` | 餐饮法规 | Gaststättengesetz、营业许可、申报制等 |
| `tax-finance` | 财税·补贴 | 增值税、培训岗位税、政府资助 |
| `labor-staffing` | 招工·人力 | 最低工资、技工短缺、移民劳工 |
| `energy-cost` | 能源·成本 | 电价、燃气、附加费 |
| `supply-food` | 食材·供应链 | 进口、价格、地理标志 |
| `hygiene-safety` | 卫生·食品安全 | LaGeSo、EFSA、检查 |
| `digital-tech` | 数字化·AI | 在线点餐、SaaS、AI 应用 |
| `real-estate` | 场地·租赁 | 商业用地、空置利用 |
| `events-marketing` | 活动·营销 | 体验式营销、节庆 |
| `trends-consumer` | 消费趋势 | 消费降级、外卖、健康餐 |
| `geopolitics-trade` | 国际·贸易 | 中美 / 中欧、能源地缘 |
| `berlin-local` | 柏林本地 | 柏林市政、区议会 |

**机制**：Claude 翻译时为每篇选 1–3 个标签写入 frontmatter；Astro 自动出 `/tags/<slug>` 页面。

`sources.json` 里旧的 `categories` 字段保留，仅用于打分（不上前端）。

---

## 5. 内容模型（Astro Content Collections）

### 5.1 articles 集合

`site/src/content/articles/<slug>.md`：

```yaml
---
title: "柏林参议院通过新《餐饮法》"        # 中译标题
titleOriginal: "Berlin verabschiedet neues Gaststättengesetz"
description: "首次现代化柏林餐饮法..."     # ≤ 160 字符
pubDate: 2026-04-12
sourceName: "Senatskanzlei Berlin"
sourceUrl: "https://www.berlin.de/.../pressemitteilung.1650966.php"
sourceLang: "de"
tags: ["gastro-law", "berlin-local"]
heroImage: ""
---

（中译全文 Markdown）

## 对柏林餐饮业的影响

（影响分析 Markdown）

---

## 原文参考

来源：[Senatskanzlei Berlin](原文链接) · 2026-03-10

> 原文摘录或全文……
```

### 5.2 briefings 集合

`site/src/content/briefings/<YYYY-MM-DD>.md`：

```yaml
---
title: "柏林餐饮商业新闻简报 — 2026-04-26"
date: 2026-04-26
audioUrl: "/berlin-gastro-news/audio/2026-04-26.mp3"
articles:
  - "berlin-gaststaettengesetz-2026-04-12"
  - "ihk-fachkraefte-2026-04-12"
  # ... 共 10 条
---

（可选导语 Markdown，由 Claude 生成）
```

### 5.3 schema 定义

`site/src/content.config.ts`：

```typescript
import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const articles = defineCollection({
  loader: glob({ base: './src/content/articles', pattern: '**/*.md' }),
  schema: z.object({
    title: z.string(),
    titleOriginal: z.string(),
    description: z.string().max(200),
    pubDate: z.coerce.date(),
    sourceName: z.string(),
    sourceUrl: z.string().url(),
    sourceLang: z.enum(['de', 'en', 'zh']).default('de'),
    tags: z.array(z.string()).min(1).max(3),
    heroImage: z.string().optional(),
  }),
});

const briefings = defineCollection({
  loader: glob({ base: './src/content/briefings', pattern: '**/*.md' }),
  schema: z.object({
    title: z.string(),
    date: z.coerce.date(),
    audioUrl: z.string().optional(),
    articles: z.array(z.string()).min(1).max(15),
  }),
});

export const collections = { articles, briefings };
```

---

## 6. 每日工作流（OpenClaw 视角）

每天 06:00 (Europe/Berlin) OpenClaw 触发，按以下 7 步执行：

```
步骤 1: python3 scripts/harvest.py
        → 从 sources.json 抓所有 RSS，自动去重入 DB

步骤 2: python3 scripts/select.py --count 10 --date today
        → 从 DB 选 Top10 unplayed → 写 daily-selected.json

步骤 3: [Claude 自身的认知工作，无脚本]
        → 读 daily-selected.json
        → 对每条新闻：
            a. WebFetch 原文（必要时；paywall 检测）
            b. 翻译标题 + 全文 + 摘要
            c. 写"对柏林餐饮业的影响"分析
            d. 选 1-3 个 industry_tags
            e. 写回 DB（translated_* 字段）
        → 生成 audio_script.md（朗读串稿）
        → 生成 briefing 导语（可选）

步骤 4: python3 scripts/publish_article.py --all-pending
        → 把 DB 里有 translated_body 但还没 slug 的全部输出到
          site/src/content/articles/<slug>.md

步骤 5: python3 scripts/publish_briefing.py --date today
        → 写 site/src/content/briefings/<date>.md
        → 同时写 daily/<YYYY>/<YYYY-MM>/<date>/{briefing.md, audio_script.md, meta.json}
        → 标记 DB 中这 10 条 broadcast_status='played', published_briefing_date=today

步骤 6: python3 scripts/render_audio.py --date today
        → 调 minimax_tts.py(daily/<date>/audio_script.md → daily/<date>/audio.mp3)
        → cp 一份到 site/public/audio/<date>.mp3

步骤 7: python3 scripts/git_publish.py --date today
        → git pull --rebase
        → git add data/ site/src/content/ site/public/audio/ daily/
        → git commit -m "📰 Daily briefing: {date}"
        → git push origin main
```

GH Action 在 push 后自动 build & deploy，约 1-2 分钟后 `https://unclejoeyao666.github.io/berlin-gastro-news/` 更新。

OpenClaw 的 Discord 子任务读 `daily/<date>/briefing.md` + `meta.json` 把链接和音频发到频道。

`workflows/DAILY_WORKFLOW.md` 是这个流程的人类可读版本，OpenClaw 把它当 slash command 蓝本。

---

## 7. Astro 站点路由

| URL | 内容 | 数据来源 |
|---|---|---|
| `/` | 当日简报头部 + 最新 5 期 + 最新 10 篇文章 | briefings + articles |
| `/briefings/<date>` | 一期简报详情（10 卡片 + 音频播放器 + 标签筛选） | briefings + 关联 articles |
| `/articles/<slug>` | 一篇文章（中译全文 + 影响分析 + 原文参考 + 标签 badge） | articles |
| `/tags/<tag>` | 该标签下所有文章（按 pubDate 倒序） | articles filter |
| `/archive` | 按月份分组 + 每月文章计数 | articles |
| `/rss.xml` | 全站 RSS（articles 最近 50 篇） | @astrojs/rss |
| `/sitemap.xml` | 自动生成 | @astrojs/sitemap |
| `/about` | 项目说明 / 数据来源 / 工作机制 | static |

### 视觉风格
- 起手抄 CashCow `seo-site/src/layouts/BlogPost.astro`
- 加暗色模式（沿用 v1 的 toggle）
- 行业标签 badge 用 12 标签固定配色（设计阶段定）
- 音频播放器：原生 HTML5 `<audio>`，无第三方依赖

---

## 8. TTS 集成

### 8.1 调用方式
```bash
python3 /Users/unclejoe/Doc_Workspace/scripts/minimax_tts.py \
  --file daily/<date>/audio_script.txt \
  daily/<date>/audio.mp3 \
  --voice zh-CN-XiaoxiaoNeural
```

`render_audio.py` 在调用前先把 `audio_script.md` 的 Markdown 标记 strip 掉（去 `#`、`*`、URL、表格分隔符），输出到 `audio_script.txt` 临时文件再喂给 TTS。

### 8.2 朗读稿结构（Claude 在步骤 3 产出）
```
开场白（约 30 秒）：
"早上好，欢迎收听柏林餐饮商业新闻简报，今天是 2026 年 4 月 26 日，星期日。
今天为您播报 10 条值得关注的新闻……"

第 1 条（约 45 秒）：
"第一条：柏林参议院通过新《餐饮法》。
柏林参议院在……（中译标题展开）
对您的影响是……（影响分析浓缩）"

[第 2-10 条]

收尾（约 15 秒）：
"以上就是今天的简报，详情请访问网站 https://unclejoeyao666.github.io/berlin-gastro-news 。
祝您生意兴隆，明天见。"
```

总时长目标 8-12 分钟。

### 8.3 默认配置
- **Provider**：Microsoft Edge TTS（免费，质量足够）
- **Voice**：`zh-CN-XiaoxiaoNeural`
- **Rate**：`+0%`
- **失败回退**：自动降级 MiniMax `speech-2.8-hd` + `male-qn-qingse`

---

## 9. 部署 / GitHub Action

`.github/workflows/deploy.yml`（基于 CashCow 模板）：

```yaml
name: Build & Deploy to GitHub Pages

on:
  push:
    branches: [main]
    paths:
      - 'site/**'
      - '.github/workflows/deploy.yml'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: site
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: 'npm'
          cache-dependency-path: site/package-lock.json
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-pages-artifact@v3
        with:
          path: ./site/dist

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

### Pages 启用步骤（一次性）
1. `gh repo create unclejoeyao666/berlin-gastro-news --public --source=. --remote=origin`
2. `git push -u origin main`
3. `gh api -X POST repos/unclejoeyao666/berlin-gastro-news/pages -f build_type=workflow`

### Astro 配置
```javascript
// site/astro.config.mjs
export default defineConfig({
  site: 'https://unclejoeyao666.github.io',
  base: '/berlin-gastro-news',
  integrations: [mdx(), sitemap()],
});
```

---

## 10. 风险与已识别坑

| # | 风险 | 应对 |
|---|---|---|
| 1 | Astro `site` + `base` 错配导致 404 / 资源路径错 | 严格抄 CashCow 配置，build 后用 `npx serve site/dist` 本地验证 |
| 2 | Spiegel/FAZ 等付费墙 → WebFetch 取不到全文 | Claude 检测正文 < 500 字符时降级为 RSS summary 扩写，文末标注 `(原文部分付费)` |
| 3 | OpenClaw 中途失败 → 重入污染 | 所有脚本支持 `--date`；publish_article 用 INSERT OR REPLACE；git_publish 前 `git pull --rebase`；DB 写入用事务 |
| 4 | 音频体积累积（每天 ~3 MB，年 ~1 GB） | 前期不处理；满 800 MB 时迁 Cloudflare R2，URL 切换 |
| 5 | GH Action 跑久了 npm 缓存失效 | 锁 Node 22 + `cache-dependency-path: site/package-lock.json` |
| 6 | 第一次部署忘记 enable Pages | spec 第 9.1 步显式列出 `gh api` 命令 |
| 7 | TTS 朗读稿包含特殊字符（"·""—"等）影响合成 | render_audio.py 的 strip 阶段做 ASCII 替换映射表 |
| 8 | DB 文件被 git 追踪可能在并发提交时冲突 | 接受冲突风险（每天只写 1 次）；冲突时 `git checkout --theirs data/news.db` 后重跑步骤 3-7 |
| 9 | 旧 v1 文件混在仓库根目录 | 第 1 步先迁到 `archive/v1/`，再开始重构 |
| 10 | OpenClaw 生成的文章 slug 冲突（同一新闻被选两次） | `news_articles.slug` 加 UNIQUE 索引；publish_article 检测冲突自动加日期后缀 |

---

## 11. Slug 命名规则

Slug 用于 Astro 路径 `/articles/<slug>`：

```
<英文关键词或拼音>-<YYYY-MM-DD>
例：berlin-gaststaettengesetz-2026-04-12
    ihk-fachkraefte-2026-04-12
```

生成规则：
1. Claude 在翻译时给出 `slug_hint`（英文/拼音 kebab-case，3-5 词）
2. `publish_article.py` 拼接 `<slug_hint>-<pubDate>`
3. 若仍冲突 → 后缀 `-2`、`-3`

最大长度 60 字符。

---

## 12. 落地顺序（Challenges 雏形）

按依赖排：

1. **仓库初始化** — 归档 v1 文件，gh repo create，初始 commit & push
2. **数据层** — 建 SQLite schema，迁移 sources.json，写 `lib/news_db.py`
3. **抓取脚本** — `harvest.py`（移植 ai-daily-news/db/harvest.py 并适配本场景的 RSS 源 + 重要性评分）
4. **数据迁移脚本** — `migrate_v1_to_sqlite.py`，跑一次把现有 JSON 灌进 DB
5. **选篇脚本** — `select.py`（DB → daily-selected.json）
6. **Astro 脚手架** — package.json + astro.config + content.config + 12 个标签的 i18n 映射
7. **Astro 布局与组件** — BaseLayout / ArticleLayout / BriefingLayout + ArticleCard / TagBadge / AudioPlayer
8. **Astro 路由** — index / briefings / articles / tags / archive / about / rss.xml
9. **发布脚本** — `publish_article.py` + `publish_briefing.py`
10. **音频脚本** — `render_audio.py`
11. **Git 推送脚本** — `git_publish.py`
12. **GH Action + Pages 启用** — `.github/workflows/deploy.yml` + `gh api` enable
13. **OpenClaw 工作流文档** — `workflows/DAILY_WORKFLOW.md`
14. **端到端 dry run** — 用今天选出的真实数据走完 1-7 步骤，验证 GH Pages 真的更新
15. **README + about 页面** — 项目说明、数据来源、工作机制
16. **(可选) 旧数据回填** — 把 `archive/v1/2026/04/<dd>/news_*.md` 中已有的 7 条手工策划新闻反向解析成 articles，作为站点冷启动内容

---

## 13. 验收标准

项目完成 = 以下 7 条同时满足：

1. `https://unclejoeyao666.github.io/berlin-gastro-news/` 可访问，首页显示当日简报 + 最近文章列表
2. `/articles/<slug>` 页面包含中译全文 + 影响分析 + 原文参考 + 标签 badge
3. `/tags/<slug>` 12 个标签页都能访问，至少有种子内容
4. `/rss.xml` 和 `/sitemap.xml` 自动生成且有效
5. 当日简报页有可播放音频（`<audio>` 标签直链 `/audio/<date>.mp3`）
6. `daily/<YYYY>/<YYYY-MM>/<date>/` 包含 briefing.md、audio_script.md、audio.mp3、meta.json 四件套
7. OpenClaw 跑一次完整的 7 步流水线，全部成功且无人工干预

---

## 14. 不做的事（明确 YAGNI）

- 不做用户登录 / 评论
- 不做搜索框（FTS5 仅限管理用，前端不暴露）
- 不做多语言版（仅中文，不出英文/德文版）
- 不做付费订阅
- 不做 PWA
- 不做手动审核流程（信任 Claude 翻译质量）
- 不做 i18n 路由（`/zh/...`），路径直接是中文友好的英文 slug
- 不做评论系统 / 社交分享按钮（v1.x 再加）
- 不做 Web Analytics（前期靠 GH Pages 内置）

---

## 15. 后续路线图（v2.x → v3）

| 版本 | 范围 |
|---|---|
| v2.0 | 本设计 |
| v2.1 | 文章页加"相关文章"、"上一篇 / 下一篇" |
| v2.2 | 简报页加 Open Graph 卡片、社交分享 |
| v2.3 | 移动端体验优化（音频固定播放器） |
| v2.4 | 邮件订阅（Buttondown） |
| v3.0 | 多语言（德语 / 英语版） |

---

**End of design.**

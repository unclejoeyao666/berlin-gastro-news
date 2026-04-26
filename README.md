# Berlin Gastro News

每日柏林餐饮商业新闻自动播报系统 — 抓取 → 翻译 → 站点发布 → 音频 → Discord。

**站点**：https://unclejoeyao666.github.io/berlin-gastro-news/
**架构设计**：[docs/superpowers/specs/2026-04-26-berlin-gastro-news-v2-design.md](docs/superpowers/specs/2026-04-26-berlin-gastro-news-v2-design.md)
**每日工作流**：[workflows/DAILY_WORKFLOW.md](workflows/DAILY_WORKFLOW.md)

## 项目结构

```
data/         SQLite 新闻数据库 + RSS 源
scripts/      Python 流水线脚本
site/         Astro 静态站点
daily/        每日成品文件包（briefing.md / audio_script.md / audio.mp3 / meta.json）
docs/         设计文档与执行计划
archive/v1/   v1 历史代码与数据
```

## 运行方式

由本地 OpenClaw 每天 06:00 (Berlin) 触发，按 `workflows/DAILY_WORKFLOW.md` 7 步流水线执行。

## License

私人项目，未授权第三方使用。

#!/usr/bin/env python3
"""
新闻静态网站生成器 - generate_site.py
从 news-db.json 生成静态HTML网站

用法: python3 generate_site.py [--date YYYY-MM-DD]
  --date 指定生成哪一天的简报（默认今天）
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter, defaultdict

BASE_DIR = Path(__file__).parent
DB_FILE = BASE_DIR / "news-db.json"
SELECTED_FILE = BASE_DIR / "selected-today.json"
SITE_DIR = BASE_DIR / "site"
BERLIN_TZ = timezone(timedelta(hours=2))

# 类别中文名
CATEGORY_CN = {
    "gastronomie": "餐饮", "business": "商业", "economy": "经济",
    "law": "法律法规", "tax": "财税", "food-safety": "食品安全",
    "berlin": "柏林", "trade": "贸易", "regulations": "监管",
    "subsidies": "补贴", "finance": "金融", "china": "中国",
    "asia": "亚洲", "geopolitics": "地缘政治", "eu": "欧盟",
    "politics": "政治", "health": "卫生", "hygiene": "卫生安全",
    "supply-chain": "供应链", "equipment": "设备", "hotellerie": "酒店",
    "events": "活动", "general": "综合", "international": "国际",
    "management": "管理", "agriculture": "农业",
}

# 类别颜色
CATEGORY_COLORS = {
    "gastronomie": "#e74c3c", "business": "#3498db", "economy": "#2980b9",
    "law": "#8e44ad", "tax": "#9b59b6", "food-safety": "#e67e22",
    "berlin": "#1abc9c", "trade": "#27ae60", "geopolitics": "#c0392b",
    "china": "#e74c3c", "eu": "#2c3e50", "politics": "#7f8c8d",
    "finance": "#f39c12", "asia": "#d35400",
}

def get_category_color(cats):
    for c in cats:
        if c in CATEGORY_COLORS:
            return CATEGORY_COLORS[c]
    return "#95a5a6"

def get_category_cn(cats):
    names = [CATEGORY_CN.get(c, c) for c in cats[:3]]
    return " · ".join(names)

CSS = """
:root {
    --bg: #ffffff; --bg2: #f8f9fa; --text: #2c3e50; --text2: #7f8c8d;
    --border: #ecf0f1; --accent: #e74c3c; --accent2: #c0392b;
    --card-bg: #ffffff; --shadow: rgba(0,0,0,0.08);
}
[data-theme="dark"] {
    --bg: #1a1a2e; --bg2: #16213e; --text: #eaeaea; --text2: #a0a0a0;
    --border: #2a2a4a; --accent: #e74c3c; --accent2: #ff6b6b;
    --card-bg: #16213e; --shadow: rgba(0,0,0,0.3);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Noto Sans SC', 'Noto Sans', -apple-system, sans-serif;
    background: var(--bg); color: var(--text);
    line-height: 1.7; transition: all 0.3s;
}
.container { max-width: 900px; margin: 0 auto; padding: 20px; }
header {
    background: linear-gradient(135deg, #2c3e50, #3498db);
    color: white; padding: 40px 0; text-align: center;
    margin-bottom: 30px; border-radius: 0 0 20px 20px;
}
header h1 { font-size: 2em; margin-bottom: 8px; }
header p { opacity: 0.85; font-size: 1.05em; }
nav {
    display: flex; gap: 15px; justify-content: center;
    margin-top: 15px; flex-wrap: wrap;
}
nav a {
    color: white; text-decoration: none; padding: 6px 16px;
    border: 1px solid rgba(255,255,255,0.3); border-radius: 20px;
    font-size: 0.9em; transition: all 0.2s;
}
nav a:hover, nav a.active {
    background: rgba(255,255,255,0.2); border-color: white;
}
.stats-bar {
    display: flex; gap: 20px; justify-content: center;
    padding: 15px; background: var(--bg2); border-radius: 12px;
    margin-bottom: 25px; flex-wrap: wrap;
}
.stat { text-align: center; }
.stat .num { font-size: 1.8em; font-weight: 700; color: var(--accent); }
.stat .label { font-size: 0.85em; color: var(--text2); }
.card {
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px; margin-bottom: 16px;
    box-shadow: 0 2px 8px var(--shadow); transition: transform 0.2s;
    border-left: 4px solid var(--accent);
}
.card:hover { transform: translateY(-2px); }
.card .num {
    display: inline-block; background: var(--accent); color: white;
    width: 28px; height: 28px; line-height: 28px; text-align: center;
    border-radius: 50%; font-size: 0.85em; font-weight: 700;
    margin-right: 10px;
}
.card h3 { display: inline; font-size: 1.1em; }
.card .meta {
    margin: 8px 0; font-size: 0.88em; color: var(--text2);
    display: flex; gap: 15px; flex-wrap: wrap; align-items: center;
}
.card .meta .tag {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 0.8em; color: white;
}
.card .summary {
    margin: 10px 0; font-size: 0.95em; line-height: 1.8;
}
.card .link a {
    color: var(--accent); text-decoration: none; font-size: 0.9em;
}
.card .link a:hover { text-decoration: underline; }
.toggle-btn {
    position: fixed; top: 15px; right: 15px; z-index: 100;
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 50%; width: 40px; height: 40px; cursor: pointer;
    font-size: 1.2em; display: flex; align-items: center; justify-content: center;
    box-shadow: 0 2px 8px var(--shadow);
}
footer {
    text-align: center; padding: 30px; color: var(--text2);
    font-size: 0.85em; border-top: 1px solid var(--border); margin-top: 40px;
}
.search-box {
    width: 100%; padding: 12px 18px; border: 2px solid var(--border);
    border-radius: 10px; font-size: 1em; margin-bottom: 20px;
    background: var(--bg); color: var(--text);
    font-family: inherit;
}
.search-box:focus { border-color: var(--accent); outline: none; }
@media(max-width:600px) {
    header h1 { font-size: 1.4em; }
    .stats-bar { gap: 10px; }
    .card { padding: 15px; }
}
"""

JS = """
function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme');
    html.setAttribute('data-theme', current === 'dark' ? 'light' : 'dark');
    localStorage.setItem('theme', html.getAttribute('data-theme'));
}
(function() {
    const saved = localStorage.getItem('theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
    else if (window.matchMedia('(prefers-color-scheme:dark)').matches)
        document.documentElement.setAttribute('data-theme', 'dark');
})();
function filterCards() {
    const q = document.getElementById('search').value.toLowerCase();
    document.querySelectorAll('.card').forEach(c => {
        c.style.display = c.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
}
"""

def load_db():
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_selected():
    if SELECTED_FILE.exists():
        with open(SELECTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def render_header(title, subtitle, active_nav="today"):
    return f"""<header>
    <h1>📰 {title}</h1>
    <p>{subtitle}</p>
    <nav>
        <a href="index.html"{' class="active"' if active_nav=="today" else ""}>📅 今日简报</a>
        <a href="database.html"{' class="active"' if active_nav=="db" else ""}>🗄️ 新闻库</a>
        <a href="archive.html"{' class="active"' if active_nav=="archive" else ""}>📚 历史归档</a>
        <a href="about.html"{' class="active"' if active_nav=="about" else ""}>ℹ️ 关于</a>
    </nav>
</header>"""

def render_card(item, idx=None):
    color = get_category_color(item.get("categories", []))
    cats_cn = get_category_cn(item.get("categories", []))
    num_html = f'<span class="num">{idx}</span>' if idx else ''
    date_str = item.get("published", "")[:10]
    summary = item.get("summary", "暂无摘要")
    if len(summary) > 300:
        summary = summary[:300] + "…"
    url = item.get("url", "#")
    return f"""<div class="card" style="border-left-color:{color}">
    {num_html}<h3>{item.get("title","")}</h3>
    <div class="meta">
        <span>📌 {item.get("source_name_cn","")}</span>
        <span>📅 {date_str}</span>
        <span class="tag" style="background:{color}">{cats_cn}</span>
    </div>
    <div class="summary">{summary}</div>
    <div class="link"><a href="{url}" target="_blank">🔗 查看原文 →</a></div>
</div>"""

def generate_index(db, selected, date_str):
    now = datetime.now(BERLIN_TZ)
    total = len(db["items"])
    presented = sum(1 for i in db["items"] if i.get("presented"))
    unpresented = total - presented

    cards = ""
    for i, item in enumerate(selected, 1):
        cards += render_card(item, i)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>每日新闻简报 — {date_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<button class="toggle-btn" onclick="toggleTheme()">🌓</button>
{render_header("每日新闻简报", f"{date_str} · 柏林 {now.strftime('%H:%M')} · 精选10条", "today")}
<div class="container">
<div class="stats-bar">
    <div class="stat"><div class="num">{total}</div><div class="label">总新闻</div></div>
    <div class="stat"><div class="num">{presented}</div><div class="label">已播报</div></div>
    <div class="stat"><div class="num">{unpresented}</div><div class="label">待播报</div></div>
    <div class="stat"><div class="num">{len(set(i['source_id'] for i in db['items']))}</div><div class="label">新闻源</div></div>
</div>
{cards}
</div>
<footer>数据来源：{len(set(i['source_id'] for i in db['items']))}个RSS源 · 自动生成于 {now.strftime('%Y-%m-%d %H:%M')}</footer>
<script>{JS}</script>
</body></html>"""
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")

def generate_database(db):
    now = datetime.now(BERLIN_TZ)
    items = sorted(db["items"], key=lambda x: x.get("published", ""), reverse=True)
    cards = ""
    for i, item in enumerate(items[:200], 1):  # 最多显示200条
        cards += render_card(item)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>新闻数据库 — 全部新闻</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<button class="toggle-btn" onclick="toggleTheme()">🌓</button>
{render_header("新闻数据库", f"共 {len(db['items'])} 条新闻 · 最新200条", "db")}
<div class="container">
<input class="search-box" id="search" type="text" placeholder="🔍 搜索新闻标题、来源、内容..." oninput="filterCards()">
{cards}
</div>
<footer>共 {len(db['items'])} 条新闻 · 仅显示最新200条</footer>
<script>{JS}</script>
</body></html>"""
    (SITE_DIR / "database.html").write_text(html, encoding="utf-8")

def generate_archive(db):
    now = datetime.now(BERLIN_TZ)
    # 按日期分组
    by_date = defaultdict(list)
    for item in db["items"]:
        date = item.get("published", "")[:10]
        if date:
            by_date[date].append(item)

    dates_html = ""
    for date in sorted(by_date.keys(), reverse=True):
        items = by_date[date]
        presented = sum(1 for i in items if i.get("presented"))
        dates_html += f'<div class="card"><h3>📅 {date}</h3>'
        dates_html += f'<div class="meta"><span>{len(items)} 条新闻</span><span>已播报 {presented} 条</span></div>'
        dates_html += f'<div class="summary">'
        for item in sorted(items, key=lambda x: x.get("priority", 0), reverse=True)[:5]:
            color = get_category_color(item.get("categories", []))
            dates_html += f'<div>• <span class="tag" style="background:{color};font-size:0.75em">{item.get("source_name_cn","")}</span> {item.get("title","")[:60]}</div>'
        if len(items) > 5:
            dates_html += f'<div style="color:var(--text2)">…还有 {len(items)-5} 条</div>'
        dates_html += '</div></div>'

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>历史归档</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<button class="toggle-btn" onclick="toggleTheme()">🌓</button>
{render_header("历史归档", f"按日期浏览 · 共 {len(by_date)} 天", "archive")}
<div class="container">
{dates_html}
</div>
<footer>共 {len(db['items'])} 条新闻 · {len(by_date)} 天</footer>
<script>{JS}</script>
</body></html>"""
    (SITE_DIR / "archive.html").write_text(html, encoding="utf-8")

def generate_about():
    html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>关于</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
<style>""" + CSS + """</style>
</head>
<body>
<button class="toggle-btn" onclick="toggleTheme()">🌓</button>
""" + render_header("关于本项目", "新闻数据库系统", "about") + """
<div class="container">
<div class="card">
<h3>🎯 项目目标</h3>
<div class="summary">
为在德国（柏林）经营餐饮业的用户，建立一套系统化的新闻情报体系。<br>
覆盖餐饮法规、商业经济、财税政策、国际政治等核心领域。
</div></div>
<div class="card">
<h3>📡 数据来源（20+ RSS源）</h3>
<div class="summary">
<strong>餐饮核心：</strong>AHGZ 餐饮酒店报、DEHOGA 柏林协会<br>
<strong>政府官方：</strong>BMEL 联邦食品农业部<br>
<strong>德国商业：</strong>Tagesschau、Spiegel、FAZ、WiWo、Manager Magazin、ZDF<br>
<strong>国际政治：</strong>南华早报、Politico EU、EUobserver、欧盟委员会<br>
<strong>食品安全：</strong>EFSA 欧洲食品安全局<br>
<strong>国际媒体：</strong>德国之声（德/英）
</div></div>
<div class="card">
<h3>⚙️ 工作机制</h3>
<div class="summary">
1. 每日自动从20+ RSS源抓取新闻<br>
2. 智能去重，建立新闻数据库<br>
3. 按优先级精选10条最有价值的新闻<br>
4. 自动生成中文摘要和影响分析<br>
5. 推送到Discord频道，同时更新本网站
</div></div>
<div class="card">
<h3>🔧 技术架构</h3>
<div class="summary">
<strong>抓取：</strong>Python + feedparser（RSS解析）<br>
<strong>数据库：</strong>JSON（news-db.json）<br>
<strong>网站：</strong>纯静态HTML/CSS/JS<br>
<strong>调度：</strong>Hermes Agent cron job（每日7:00柏林时间）<br>
<strong>投递：</strong>Discord + 静态网站
</div></div>
</div>
<footer>Houyi（后羿）新闻系统 · 自动更新</footer>
<script>""" + JS + """</script>
</body></html>"""
    (SITE_DIR / "about.html").write_text(html, encoding="utf-8")

def main():
    date_str = datetime.now(BERLIN_TZ).strftime("%Y-%m-%d")
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            date_str = sys.argv[idx + 1]

    SITE_DIR.mkdir(parents=True, exist_ok=True)

    db = load_db()
    selected = load_selected()

    print(f"🏗️  生成静态网站 — {date_str}")
    generate_index(db, selected, date_str)
    print(f"  ✅ index.html（今日简报）")
    generate_database(db)
    print(f"  ✅ database.html（新闻库 · {len(db['items'])}条）")
    generate_archive(db)
    print(f"  ✅ archive.html（历史归档）")
    generate_about()
    print(f"  ✅ about.html（关于）")
    print(f"\n📁 输出目录: {SITE_DIR}")
    print(f"🌐 本地预览: file://{SITE_DIR.resolve()}/index.html")

if __name__ == "__main__":
    main()

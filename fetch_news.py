#!/usr/bin/env python3
"""
新闻数据库抓取脚本 - fetch_news.py
从所有RSS源抓取新闻，去重后存入news-db.json

用法: python3 fetch_news.py [--select N]
  --select N  : 同时选出N条未播报的新闻（用于每日播报）
"""

import json
import hashlib
import re
import sys
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser

# 路径配置
BASE_DIR = Path(__file__).parent
SOURCES_FILE = BASE_DIR / "sources.json"
DB_FILE = BASE_DIR / "news-db.json"

# 时区
BERLIN_TZ = timezone(timedelta(hours=2))  # CEST (夏令时)
NOW = datetime.now(BERLIN_TZ)

# 类别权重 - 用于新闻排序（越高越优先）
CATEGORY_WEIGHTS = {
    "gastronomie": 10,
    "law": 9,
    "tax": 9,
    "food-safety": 8,
    "business": 7,
    "economy": 7,
    "berlin": 6,
    "trade": 6,
    "regulations": 6,
    "subsidies": 5,
    "finance": 5,
    "china": 5,
    "asia": 4,
    "geopolitics": 4,
    "eu": 4,
    "politics": 3,
    "health": 3,
    "hygiene": 3,
    "supply-chain": 2,
    "equipment": 2,
    "hotellerie": 2,
    "events": 1,
    "general": 1,
    "international": 1,
    "management": 1,
    "agriculture": 1,
}

def load_sources():
    """加载新闻源配置"""
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["sources"]

def load_db():
    """加载新闻数据库"""
    if DB_FILE.exists():
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"items": [], "meta": {"created": NOW.isoformat(), "total_fetched": 0, "total_presented": 0}}

def save_db(db):
    """保存新闻数据库"""
    db["meta"]["last_updated"] = NOW.isoformat()
    db["meta"]["total_fetched"] = len(db["items"])
    db["meta"]["total_presented"] = sum(1 for i in db["items"] if i.get("presented"))
    db["meta"]["total_unpresented"] = sum(1 for i in db["items"] if not i.get("presented") and i.get("status") == "active")
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def make_item_id(url, title):
    """生成新闻条目唯一ID（基于URL和标题的哈希）"""
    raw = (url or "") + "|" + (title or "")
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def clean_html(text):
    """清理HTML标签"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:500]  # 限制摘要长度

def parse_date(entry):
    """解析RSS条目的日期"""
    for field in ['published_parsed', 'updated_parsed']:
        t = entry.get(field)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except:
                pass
    return NOW.isoformat()

def compute_priority(item):
    """计算新闻优先级分数（越高越重要）"""
    score = 0
    # 来源权重
    tier = item.get("source_tier", 2)
    score += (3 - tier) * 20  # tier 1 = 40, tier 2 = 20
    # 类别权重
    for cat in item.get("categories", []):
        score += CATEGORY_WEIGHTS.get(cat, 0)
    # 时效性（越新越高）
    try:
        pub_date = datetime.fromisoformat(item["published"])
        hours_old = (NOW - pub_date).total_seconds() / 3600
        if hours_old < 24:
            score += 15
        elif hours_old < 48:
            score += 10
        elif hours_old < 72:
            score += 5
    except:
        pass
    return score

def fetch_source(source):
    """从单个RSS源抓取新闻"""
    items = []
    feed_url = source["feed_url"]
    try:
        feed = feedparser.parse(feed_url)
        if feed.bozo and not feed.entries:
            print(f"  ⚠️  {source['name']}: Feed解析错误 - {feed.bozo_exception}")
            return items

        for entry in feed.entries:
            url = entry.get("link", "")
            title = clean_html(entry.get("title", ""))
            if not title:
                continue

            item_id = make_item_id(url, title)
            summary = clean_html(entry.get("summary", entry.get("description", "")))

            items.append({
                "id": item_id,
                "title": title,
                "url": url,
                "summary": summary,
                "published": parse_date(entry),
                "source_id": source["id"],
                "source_name": source["name"],
                "source_name_cn": source.get("name_cn", source["name"]),
                "source_tier": source.get("tier", 2),
                "categories": source.get("categories", []),
                "lang": source.get("lang", "de"),
                "fetched_at": NOW.isoformat(),
                "presented": False,
                "presented_at": None,
                "status": "active",
                "priority": 0,  # 稍后计算
            })

        print(f"  ✅ {source['name']}: {len(items)} 条")
    except Exception as e:
        print(f"  ❌ {source['name']}: {e}")
    return items

# 已知的非新闻URL模式（导航页、分类页、静态页面）
NOISE_URL_PATTERNS = [
    r'/sen/wirtschaft/konjunktur',
    r'/sen/wirtschaft/gruenden',
    r'/sen/wirtschaft/digitalisierung',
    r'/sen/wirtschaft/startups',
    r'/sen/wirtschaft/netzwerk',
    r'/sen/wirtschaft/europa-und-internationales',
    r'/sen/wirtschaft/foerderprogramme',
    r'/sen/wirtschaft/projekte',
    r'/sen/gesundheit/.*service/',
    r'/sen/gesundheit/.*angebote/',
]

def is_noise_item(item):
    """过滤掉导航页、分类页等非新闻条目"""
    url = item.get("url", "")
    for pattern in NOISE_URL_PATTERNS:
        if re.search(pattern, url):
            return True
    # 过滤标题过短（通常只是分类名）且没有摘要的条目
    if len(item.get("title", "")) < 10 and not item.get("summary"):
        return True
    return False

def is_duplicate(new_item, existing_items):
    """检查是否与已有条目重复"""
    for existing in existing_items:
        # URL完全匹配
        if new_item["url"] and existing["url"] and new_item["url"] == existing["url"]:
            return True, existing["id"]
        # 标题高度相似（去除标点后完全匹配）
        t1 = re.sub(r'[^\w\s]', '', new_item["title"].lower())
        t2 = re.sub(r'[^\w\s]', '', existing["title"].lower())
        if t1 and t2 and t1 == t2:
            return True, existing["id"]
    return False, None

def select_top_items(db, count=10):
    """选出N条最有价值的未播报新闻"""
    # 获取未播报且状态为active的条目
    candidates = [
        item for item in db["items"]
        if not item.get("presented") and item.get("status") == "active"
    ]

    # 重新计算优先级（考虑当前时间）
    for item in candidates:
        item["priority"] = compute_priority(item)

    # 按优先级排序
    candidates.sort(key=lambda x: x["priority"], reverse=True)

    # 优先选当天的，不足则从旧库补充
    today_str = NOW.strftime("%Y-%m-%d")
    today_items = [i for i in candidates if i["published"].startswith(today_str)]
    older_items = [i for i in candidates if not i["published"].startswith(today_str)]

    selected = today_items[:count]
    if len(selected) < count:
        selected.extend(older_items[:count - len(selected)])

    return selected[:count]

def mark_presented(db, item_ids):
    """标记新闻为已播报"""
    id_set = set(item_ids)
    for item in db["items"]:
        if item["id"] in id_set:
            item["presented"] = True
            item["presented_at"] = NOW.isoformat()

def main():
    """主流程"""
    select_count = None
    if "--select" in sys.argv:
        idx = sys.argv.index("--select")
        if idx + 1 < len(sys.argv):
            select_count = int(sys.argv[idx + 1])

    print(f"📰 新闻数据库抓取 - {NOW.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"=" * 50)

    # 加载数据
    sources = load_sources()
    db = load_db()
    existing_ids = {item["id"] for item in db["items"]}

    print(f"\n📡 正在从 {len(sources)} 个RSS源抓取...\n")

    total_new = 0
    total_dup = 0

    for source in sources:
        if not source.get("active", True):
            continue

        new_items = fetch_source(source)
        noise_count = 0
        for item in new_items:
            # 过滤噪音（导航页、分类页等）
            if is_noise_item(item):
                noise_count += 1
                continue
            is_dup, dup_id = is_duplicate(item, db["items"])
            if is_dup:
                total_dup += 1
                continue
            if item["id"] in existing_ids:
                total_dup += 1
                continue

            item["priority"] = compute_priority(item)
            db["items"].append(item)
            existing_ids.add(item["id"])
            total_new += 1

        # 礼貌延迟，避免被限速
        time.sleep(0.3)

    print(f"\n{'=' * 50}")
    print(f"📊 抓取完成:")
    print(f"   新增: {total_new} 条")
    print(f"   重复跳过: {total_dup} 条")
    print(f"   数据库总量: {len(db['items'])} 条")
    unpresented = sum(1 for i in db["items"] if not i.get("presented") and i.get("status") == "active")
    print(f"   待播报: {unpresented} 条")

    # 保存数据库
    save_db(db)
    print(f"\n💾 数据库已保存: {DB_FILE}")

    # 如果指定了 --select，选出Top N
    if select_count:
        print(f"\n🎯 精选 Top {select_count}:")
        print(f"-" * 50)
        selected = select_top_items(db, select_count)
        if not selected:
            print("   （没有待播报的新闻）")
        else:
            for i, item in enumerate(selected, 1):
                print(f"\n  [{i}] {item['title']}")
                print(f"      来源: {item['source_name_cn']} | {item['published'][:10]}")
                print(f"      优先级: {item['priority']} | 类别: {', '.join(item['categories'])}")
                if item['url']:
                    print(f"      🔗 {item['url']}")

        # 输出选中条目的JSON（供cron job使用）
        select_output = BASE_DIR / "selected-today.json"
        with open(select_output, "w", encoding="utf-8") as f:
            json.dump(selected, f, ensure_ascii=False, indent=2)
        print(f"\n   选中结果已保存: {select_output}")

if __name__ == "__main__":
    main()

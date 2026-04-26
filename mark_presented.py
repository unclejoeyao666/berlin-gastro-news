#!/usr/bin/env python3
"""
标记新闻为已播报 - mark_presented.py
播报成功后调用，将选中的新闻标记为已播报

用法: python3 mark_presented.py [selected-today.json路径]
  不指定路径则使用默认的 selected-today.json
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_FILE = BASE_DIR / "news-db.json"
BERLIN_TZ = timezone(timedelta(hours=2))

def main():
    now = datetime.now(BERLIN_TZ)
    
    # 确定输入文件
    if len(sys.argv) > 1:
        selected_file = Path(sys.argv[1])
    else:
        selected_file = BASE_DIR / "selected-today.json"
    
    if not selected_file.exists():
        print(f"❌ 未找到选中文件: {selected_file}")
        sys.exit(1)
    
    # 加载选中的条目
    with open(selected_file, "r", encoding="utf-8") as f:
        selected = json.load(f)
    
    if not selected:
        print("ℹ️ 没有需要标记的条目")
        return
    
    selected_ids = {item["id"] for item in selected}
    
    # 加载数据库
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
    
    # 标记
    marked = 0
    for item in db["items"]:
        if item["id"] in selected_ids and not item.get("presented"):
            item["presented"] = True
            item["presented_at"] = now.isoformat()
            marked += 1
    
    # 保存
    db["meta"]["last_updated"] = now.isoformat()
    db["meta"]["total_presented"] = sum(1 for i in db["items"] if i.get("presented"))
    db["meta"]["total_unpresented"] = sum(
        1 for i in db["items"] 
        if not i.get("presented") and i.get("status") == "active"
    )
    
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 已标记 {marked} 条新闻为已播报")
    print(f"   数据库总量: {len(db['items'])} 条")
    print(f"   已播报: {db['meta']['total_presented']} 条")
    print(f"   待播报: {db['meta']['total_unpresented']} 条")

if __name__ == "__main__":
    main()

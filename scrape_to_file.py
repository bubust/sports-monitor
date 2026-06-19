"""
scrape_to_file.py — GitHub Actions 用，抓資料後存成 data/latest.json
"""
import os, json, time, logging
from pathlib import Path
from scraper import SportsScraper
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

Path("data").mkdir(exist_ok=True)

scraper = SportsScraper()
scraper.start()

try:
    data = scraper.scrape_all()
    out = {
        "status":     "正常" if data.get("strategies") else "失敗",
        "error":      data.get("error", ""),
        "updated_at": data.get("timestamp", ""),
        "data":       data,
    }
    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"✓ 抓取完成，共 {len(data.get('strategies', {}))} 個策略")
except Exception as e:
    print(f"✗ 抓取失敗：{e}")
    raise
finally:
    scraper.stop()

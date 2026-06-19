"""
app.py — 從 GitHub raw 讀取資料，請求時直接抓（無背景執行緒）
"""
import time
import logging
import json
import urllib.request
from flask import Flask, render_template, jsonify
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

GITHUB_RAW = (
    "https://raw.githubusercontent.com/bubust/sports-monitor/master/data/latest.json"
)

# 簡單 in-memory 快取：每 2 分鐘從 GitHub 重新抓一次
_cache = {"data": None, "fetched_at": 0}


def _fetch_github():
    """從 GitHub 拿最新資料，成功就更新快取"""
    try:
        req = urllib.request.Request(
            GITHUB_RAW,
            headers={
                "User-Agent":     "sports-monitor/1.0",
                "Cache-Control":  "no-cache",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
        _cache["data"] = json.loads(raw)
        _cache["fetched_at"] = time.time()
        logger.info(f"GitHub 資料更新成功，策略數: "
                    f"{len((_cache['data'].get('data') or {}).get('strategies', {}))}")
    except Exception as e:
        logger.error(f"讀取 GitHub 失敗：{e}")


# ---------------------------------------------------------------
# 路由
# ---------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    # 超過 2 分鐘或還沒抓過，就重新抓
    if time.time() - _cache["fetched_at"] > 120:
        _fetch_github()

    d = _cache.get("data")
    if not d:
        return jsonify({
            "status":     "等待資料中...",
            "error":      "GitHub 尚無資料，請等 Actions 執行完畢",
            "updated_at": "",
            "data":       None,
        })

    return jsonify({
        "status":     d.get("status", "正常"),
        "error":      d.get("error", ""),
        "updated_at": d.get("updated_at", ""),
        "data":       d.get("data"),
    })


@app.route("/api/status")
def api_status():
    d = _cache.get("data")
    return jsonify({
        "status":     d.get("status", "未知") if d else "初始化中",
        "updated_at": d.get("updated_at", "") if d else "",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)

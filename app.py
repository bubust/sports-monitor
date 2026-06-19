"""
app.py — 從 GitHub raw 讀取抓取結果並提供 API
"""
import threading
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

# GitHub raw JSON 位置
GITHUB_RAW = "https://raw.githubusercontent.com/bubust/sports-monitor/master/data/latest.json"

_cache = {
    "data":       None,
    "status":     "初始化中，請稍候...",
    "updated_at": "",
    "error":      "",
}
_lock = threading.Lock()


# ---------------------------------------------------------------
# 背景：每 2 分鐘從 GitHub 拉一次資料
# ---------------------------------------------------------------
def _fetch_loop():
    while True:
        try:
            req = urllib.request.Request(
                GITHUB_RAW,
                headers={"User-Agent": "sports-monitor/1.0", "Cache-Control": "no-cache"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            with _lock:
                _cache["data"]       = data.get("data")
                _cache["status"]     = data.get("status", "正常")
                _cache["error"]      = data.get("error", "")
                _cache["updated_at"] = data.get("updated_at", "")
            logger.info(f"資料已從 GitHub 更新，策略數: {len((data.get('data') or {}).get('strategies', {}))}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                with _lock:
                    _cache["status"] = "等待第一次抓取..."
                    _cache["error"]  = "GitHub 尚無資料"
                logger.warning("GitHub 資料尚未存在（404）")
            else:
                logger.error(f"讀取 GitHub 失敗 HTTP {e.code}")
        except Exception as e:
            logger.error(f"讀取 GitHub 失敗：{e}")

        time.sleep(120)


threading.Thread(target=_fetch_loop, daemon=True).start()


# ---------------------------------------------------------------
# 路由
# ---------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    with _lock:
        return jsonify({
            "status":     _cache["status"],
            "error":      _cache["error"],
            "updated_at": _cache["updated_at"],
            "data":       _cache["data"],
        })


@app.route("/api/status")
def api_status():
    with _lock:
        return jsonify({
            "status":     _cache["status"],
            "updated_at": _cache["updated_at"],
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)

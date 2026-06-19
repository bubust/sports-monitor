"""
app.py — Flask 後端 + 背景抓取執行緒
"""

import threading
import time
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify
from scraper import SportsScraper
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _restart_scraper(scraper):
    try:
        scraper.stop()
    except Exception:
        pass


def _new_scraper():
    s = SportsScraper()
    s.start()
    return s

# ---------------------------------------------------------------
# 全域資料快取
# ---------------------------------------------------------------
_cache = {
    "data":      None,
    "status":    "初始化中，請稍候...",
    "updated_at": "",
    "error":     "",
}
_lock = threading.Lock()


# ---------------------------------------------------------------
# 背景抓取執行緒
# ---------------------------------------------------------------
def _scraper_loop():
    scraper = _new_scraper()

    while True:
        try:
            logger.info("── 開始抓取 ──")
            data = scraper.scrape_all()

            with _lock:
                _cache["data"]      = data
                _cache["status"]    = "正常"
                _cache["error"]     = ""
                _cache["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"抓取完成，共 {len(data.get('strategies', {}))} 個策略")

        except Exception as e:
            logger.error(f"抓取例外：{e}", exc_info=True)
            with _lock:
                _cache["status"] = f"例外錯誤"
                _cache["error"]  = str(e)
            _restart_scraper(scraper)
            scraper = _new_scraper()
            time.sleep(10)
            continue

        # 登入失敗時也重啟瀏覽器
        if "error" in data and not data.get("strategies"):
            err_msg = data.get("error", "")
            logger.warning(f"抓取失敗（{err_msg}），重啟瀏覽器...")
            with _lock:
                _cache["status"] = "抓取失敗，重試中..."
                _cache["error"]  = err_msg
            _restart_scraper(scraper)
            scraper = _new_scraper()
            time.sleep(10)
            continue

        time.sleep(config.SCRAPE_INTERVAL)


# ---------------------------------------------------------------
# 路由
# ---------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", port=config.PORT)


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


@app.route("/api/debug")
def api_debug():
    """臨時除錯：測試能否連到目標網站並找到登入表單"""
    import requests as req
    from bs4 import BeautifulSoup
    import config as cfg
    result = {}
    try:
        r = req.get(cfg.BASE_URL, timeout=15,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0"})
        result["status_code"] = r.status_code
        result["final_url"] = r.url
        soup = BeautifulSoup(r.content, "html.parser")
        form = soup.find("form")
        result["form_found"] = form is not None
        if form:
            result["form_action"] = form.get("action", "")
            inputs = [{"type": i.get("type",""), "name": i.get("name",""), "placeholder": i.get("placeholder","")}
                      for i in form.find_all("input")]
            result["inputs"] = inputs
        result["body_snippet"] = r.text[:300]
    except Exception as e:
        result["error"] = str(e)
    return jsonify(result)


# ---------------------------------------------------------------
# 啟動（gunicorn 或直接執行皆可）
# ---------------------------------------------------------------
def _start_background():
    t = threading.Thread(target=_scraper_loop, daemon=True)
    t.start()

_start_background()

if __name__ == "__main__":
    logger.info(f"儀表板已啟動：http://localhost:{config.PORT}")
    app.run(host="0.0.0.0", port=config.PORT, debug=False, use_reloader=False)

# ============================================================
#  sports-monitor 設定檔 — 可自行修改
# ============================================================

import os

USERNAME      = os.environ.get("SPORTS_USER", "bubust@gmail.com")
PASSWORD      = os.environ.get("SPORTS_PASS", "1234567")
TOTP_SECRET   = os.environ.get("SPORTS_TOTP", "2EU3UPWU3LY5PMOW")

BASE_URL      = "https://sports.icux.xyz/"

# 自動抓取間隔（秒），建議 90~180，太頻繁容易被擋
SCRAPE_INTERVAL = 120

# 瀏覽器視窗 — False=顯示視窗(除錯用), True=背景靜默
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

# Web 伺服器 port
PORT = int(os.environ.get("PORT", 5566))

# ── 要監測的頁面（名稱: URL）────────────────────────────────
PAGES = {
    "獨贏一": "https://sports.icux.xyz/football/index1.php?t=21",
    "獨贏二": "https://sports.icux.xyz/football/index1.php?t=6",
    "大分二": "https://sports.icux.xyz/football/index3.php?t=2",
    "大分三": "https://sports.icux.xyz/football/index3.php?t=3",
    "策略一": "https://sports.icux.xyz/football/index5.php?t=6",
    "策略二": "https://sports.icux.xyz/football/index5.php?t=2",
    "策略四": "https://sports.icux.xyz/football/index7.php?t=0",
    "策略五": "https://sports.icux.xyz/football/index7.php?t=2",
    "隊伍三": "https://sports.icux.xyz/football/index7.php?t=4",
    "數據一": "https://sports.icux.xyz/football/index9.php?t=0",
    "數據二": "https://sports.icux.xyz/football/index9.php?t=2",
    "數據三": "https://sports.icux.xyz/football/index9.php?t=4",
}

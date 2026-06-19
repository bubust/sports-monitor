"""
scraper.py — Playwright 自動登入 + 抓取各策略頁面
"""

import time
import logging
import pyotp
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from bs4 import BeautifulSoup
from datetime import datetime
import config

logger = logging.getLogger(__name__)

# 策略頁面關鍵字（對應導覽列文字）
STRATEGIES = ["獨贏", "大小", "賽事", "假賽", "非常用賽"]
PAGE_TYPES  = ["面板", "即時", "統計"]


class SportsScraper:
    def __init__(self):
        self._pw        = None
        self._browser   = None
        self._ctx       = None
        self.page       = None
        self.logged_in  = False
        self.nav_links  = {}   # {strategy: {page_type: url}}

    # ------------------------------------------------------------------
    # 生命週期
    # ------------------------------------------------------------------
    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=config.HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )
        self._ctx = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1600, "height": 900},
            locale="zh-TW",
        )
        self._ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW','zh','en']});
            window.chrome = { runtime: {} };
        """)

        # 從 Chrome 讀取 Cookie 並注入
        self._inject_chrome_cookies()

        self.page = self._ctx.new_page()
        logger.info("瀏覽器已啟動")

    def _inject_chrome_cookies(self):
        """從本機 Chrome 讀取 Cookie 並注入 Playwright context"""
        try:
            import browser_cookie3
            cj = browser_cookie3.chrome(domain_name='icux.xyz')
            cookies = []
            for c in cj:
                cookie = {
                    "name":   c.name,
                    "value":  c.value,
                    "domain": c.domain if c.domain else '.icux.xyz',
                    "path":   c.path or '/',
                }
                if c.expires and c.expires > 0:
                    cookie["expires"] = float(c.expires)
                cookies.append(cookie)

            if cookies:
                self._ctx.add_cookies(cookies)
                logger.info(f"已注入 {len(cookies)} 個 Chrome Cookie")
                self.logged_in = True   # 有 Cookie 先假設已登入
            else:
                logger.warning("找不到 icux.xyz 的 Cookie，需要重新登入")
        except Exception as e:
            logger.warning(f"讀取 Chrome Cookie 失敗：{e}，將嘗試手動登入")

    def stop(self):
        try:
            if self._ctx:
                self._ctx.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        logger.info("瀏覽器已關閉")

    # ------------------------------------------------------------------
    # TOTP
    # ------------------------------------------------------------------
    def _totp(self):
        totp = pyotp.TOTP(config.TOTP_SECRET)
        # 距離下個週期不足 8 秒就等新的，避免送出時已過期
        remaining = 30 - (int(time.time()) % 30)
        if remaining < 8:
            logger.info(f"TOTP 即將過期（剩 {remaining}s），等下一個週期...")
            time.sleep(remaining + 1)
        code = totp.now()
        remaining2 = 30 - (int(time.time()) % 30)
        logger.info(f"TOTP: {code}（剩 {remaining2}s）")
        return code

    # ------------------------------------------------------------------
    # 登入
    # ------------------------------------------------------------------
    def login(self) -> bool:
        logger.info("前往登入頁...")
        try:
            self.page.goto(config.BASE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # 如果已經在主頁，不需要登入
            if self._is_main_page():
                logger.info("已登入")
                self.logged_in = True
                return True

            # 填帳號（第 1 個 text input）
            try:
                self.page.locator('input[type="text"]').first.fill(config.USERNAME, timeout=5000)
                logger.info("填入帳號")
            except Exception as e:
                logger.warning(f"填帳號失敗：{e}")

            # 填密碼
            try:
                self.page.fill('input[type="password"]', config.PASSWORD, timeout=5000)
                logger.info("填入密碼")
            except Exception as e:
                logger.warning(f"填密碼失敗：{e}")

            # 填認證碼（第 2 個 text input）
            try:
                code = self._totp()
                logger.info(f"輸入 TOTP: {code}")
                self.page.locator('input[type="text"]').nth(1).fill(code, timeout=3000)
                logger.info("TOTP 已填入（第 2 個 text input）")
            except Exception as e:
                logger.warning(f"填 TOTP 失敗：{e}")

            # 送出（只送一次）
            self._click_submit()
            time.sleep(5)
            # 等頁面完全載入
            try:
                self.page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            if self._is_main_page():
                logger.info("登入成功！")
                self.logged_in = True
                return True
            else:
                logger.error("登入失敗，頁面內容：" + self.page.content()[:500])
                self.page.screenshot(path="debug_login_fail.png")
                return False

        except Exception as e:
            logger.error(f"login() 例外：{e}")
            try:
                self.page.screenshot(path="debug_exception.png")
            except Exception:
                pass
            return False

    def _click_submit(self):
        for sel in ['button[type="submit"]', 'input[type="submit"]',
                    'button.btn-primary', 'button.btn', 'button']:
            try:
                self.page.click(sel, timeout=3000)
                self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                return
            except Exception:
                continue

    def _is_main_page(self) -> bool:
        try:
            content = self.page.content()
            url = self.page.url
            logger.info(f"目前 URL: {url}")
            # 有這些代表還在登入頁或登入失敗
            fail_signs = ["驗證碼輸入錯誤", "請先登入", "會員登入", "0x403", "0x401"]
            if any(k in content for k in fail_signs):
                return False
            # 還停在登入頁 URL（BASE_URL 且有登入表單）
            if "會員帳號" in content or "input[type" in content.lower():
                return False
            return True
        except Exception:
            return False

    def _need_totp(self) -> bool:
        content = self.page.content()
        return any(k in content for k in ["驗證碼", "OTP", "otp", "authenticator",
                                           "兩步驟", "2FA", "動態"])

    # ------------------------------------------------------------------
    # 取得導覽列連結
    # ------------------------------------------------------------------
    def _parse_nav(self):
        """解析當前頁面的導覽列，建立 nav_links 字典"""
        content = self.page.content()
        soup = BeautifulSoup(content, "lxml")
        links = {}

        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)
            if not href or href == "#":
                continue

            # 轉成絕對 URL
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://sports.icux.xyz" + href
            elif not href.startswith("http"):
                href = "https://sports.icux.xyz/" + href

            for strategy in STRATEGIES:
                for ptype in PAGE_TYPES:
                    if strategy in text and ptype in text:
                        links.setdefault(strategy, {})[ptype] = href

        self.nav_links = links
        logger.info(f"導覽連結：{links}")
        # debug：印出頁面上所有連結（前 30 個）
        all_links = [(a.get_text(strip=True), a.get("href","")) for a in soup.find_all("a", href=True)]
        logger.info(f"頁面所有連結（前30）：{all_links[:30]}")

    # ------------------------------------------------------------------
    # 解析單一頁面
    # ------------------------------------------------------------------
    def _parse_page(self) -> dict:
        content = self.page.content()
        soup = BeautifulSoup(content, "lxml")
        sections = []

        # 找出所有 「即時隊伍 XX (Min)」的段落
        # 通常是 <b> 或 <th> 文字，後面跟著一個 <table>
        # 也可能整張是一個大 table，第一列是標頭

        # 嘗試找到含「即時隊伍」、「面板」、「統計」的 table
        tables = soup.find_all("table")
        for tbl in tables:
            # 找標題（table 前的文字 或 table 第一個 th colspan）
            title = ""
            prev = tbl.find_previous(["b", "strong", "h3", "h4", "div"])
            if prev:
                title = prev.get_text(strip=True)

            # 尋找 colspan header 作為標題
            first_th = tbl.find("th")
            if first_th:
                th_text = first_th.get_text(strip=True)
                if any(k in th_text for k in ["即時隊伍", "隊伍", "面板", "統計"]):
                    title = th_text

            rows = tbl.find_all("tr")
            if len(rows) < 2:
                continue

            # 找 header row（包含 th 或文字類似欄位名的 td）
            headers = []
            data_start = 0
            for i, row in enumerate(rows):
                cells = row.find_all(["th", "td"])
                texts = [c.get_text(strip=True) for c in cells]
                if any(k in " ".join(texts) for k in ["時間", "數據", "參考", "隊伍"]):
                    headers = texts
                    data_start = i + 1
                    if not title:
                        # 如果 header 第一欄有「即時隊伍」等
                        title = texts[0] if texts else ""
                    break

            matches = []
            total = 0
            for row in rows[data_start:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                row_text = " ".join(c.get_text(strip=True) for c in cells)
                # 「總場次」行
                if "總場次" in row_text:
                    try:
                        total = int(row_text.split(":")[-1].strip())
                    except Exception:
                        total = 0
                    continue

                if len(cells) < 2:
                    continue

                # 第一欄可能是比賽連結
                link_tag = cells[0].find("a")
                match_entry = {
                    "team":      link_tag.get_text(strip=True) if link_tag else cells[0].get_text(strip=True),
                    "team_url":  link_tag.get("href", "") if link_tag else "",
                    "cols":      [c.get_text(strip=True) for c in cells],
                    "highlight": _row_highlight(row),
                }
                matches.append(match_entry)

            if matches or total:
                sections.append({
                    "title":   title,
                    "headers": headers,
                    "matches": matches,
                    "total":   total,
                })

        # 取頁面頂部更新資訊
        update_info = ""
        for tag in soup.find_all(["div", "p", "span"]):
            t = tag.get_text(strip=True)
            if "更新" in t and len(t) < 200:
                update_info = t
                break

        return {
            "url":         self.page.url,
            "update_info": update_info,
            "sections":    sections,
            "scraped_at":  datetime.now().strftime("%H:%M:%S"),
        }

    # ------------------------------------------------------------------
    # 主要抓取流程
    # ------------------------------------------------------------------
    def scrape_all(self) -> dict:
        if not self.logged_in:
            if not self.login():
                return {"error": "登入失敗", "timestamp": datetime.now().isoformat(),
                        "strategies": {}}

        result = {
            "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategies": {},
        }

        for name, url in config.PAGES.items():
            try:
                logger.info(f"抓取 {name} : {url}")
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(1.5)

                # 被登出了
                if "請先登入" in self.page.content() or "會員帳號" in self.page.content():
                    self.logged_in = False
                    logger.warning("Session 失效，重新登入...")
                    if not self.login():
                        result["error"] = "重新登入失敗"
                        return result
                    self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(1.5)

                result["strategies"][name] = self._parse_page()

            except Exception as e:
                logger.error(f"{name} 抓取失敗：{e}")
                result["strategies"][name] = {
                    "error": str(e), "sections": [], "scraped_at": ""
                }

        return result


# ------------------------------------------------------------------
# 輔助函式
# ------------------------------------------------------------------
def _row_highlight(row_tag) -> str:
    """根據 <tr> 的 bgcolor / class 判斷顏色（用於前端顯色）"""
    bg = row_tag.get("bgcolor", "").lower()
    cls = " ".join(row_tag.get("class", [])).lower()
    if bg in ("#ffcccc", "red", "#ff9999") or "red" in cls:
        return "danger"
    if bg in ("#ccffcc", "green", "#99ff99") or "green" in cls or "success" in cls:
        return "success"
    if bg in ("#ffffcc", "yellow", "#ffff99") or "yellow" in cls:
        return "warning"
    if "gray" in bg or "grey" in bg or "gray" in cls:
        return "secondary"
    return ""

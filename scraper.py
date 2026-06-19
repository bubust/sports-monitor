"""
scraper.py — Playwright 版本，給 GitHub Actions 用（scrape_to_file.py 呼叫）
"""

import time
import logging
import pyotp
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from bs4 import BeautifulSoup
from datetime import datetime
import config

logger = logging.getLogger(__name__)


class SportsScraper:
    def __init__(self):
        self._pw      = None
        self._browser = None
        self._ctx     = None
        self.page     = None
        self.logged_in = False

    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=config.HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
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
            window.chrome = { runtime: {} };
        """)
        self.page = self._ctx.new_page()
        logger.info("瀏覽器已啟動")

    def stop(self):
        try:
            if self._ctx:    self._ctx.close()
            if self._browser: self._browser.close()
            if self._pw:     self._pw.stop()
        except Exception:
            pass
        logger.info("瀏覽器已關閉")

    # ------------------------------------------------------------------
    # TOTP
    # ------------------------------------------------------------------
    def _totp(self):
        totp = pyotp.TOTP(config.TOTP_SECRET)
        remaining = 30 - (int(time.time()) % 30)
        if remaining < 8:
            logger.info(f"TOTP 即將過期（剩 {remaining}s），等下一個週期...")
            time.sleep(remaining + 1)
        code = totp.now()
        logger.info(f"TOTP: {code}（剩 {30-(int(time.time())%30)}s）")
        return code

    # ------------------------------------------------------------------
    # 登入
    # ------------------------------------------------------------------
    def login(self) -> bool:
        logger.info("前往登入頁...")
        try:
            self.page.goto(config.BASE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

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
                self.page.locator('input[type="text"]').nth(1).fill(code, timeout=3000)
                logger.info("TOTP 已填入")
            except Exception as e:
                logger.warning(f"填 TOTP 失敗：{e}")

            # 送出
            self._click_submit()
            time.sleep(5)
            try:
                self.page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            if self._is_main_page():
                logger.info("登入成功！")
                self.logged_in = True
                return True
            else:
                logger.error("登入失敗，頁面：" + self.page.content()[:300])
                self.page.screenshot(path="debug_login_fail.png")
                return False

        except Exception as e:
            logger.error(f"login() 例外：{e}")
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
            fail_signs = ["驗證碼輸入錯誤", "請先登入", "會員登入", "0x403", "0x401"]
            if any(k in content for k in fail_signs):
                return False
            if "會員帳號" in content:
                return False
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 解析頁面
    # ------------------------------------------------------------------
    def _parse_page(self) -> dict:
        content = self.page.content()
        soup = BeautifulSoup(content, "lxml")
        sections = []
        tables = soup.find_all("table")

        for tbl in tables:
            title = ""
            prev = tbl.find_previous(["b", "strong", "h3", "h4", "div"])
            if prev:
                title = prev.get_text(strip=True)
            first_th = tbl.find("th")
            if first_th:
                th_text = first_th.get_text(strip=True)
                if any(k in th_text for k in ["即時隊伍", "隊伍", "面板", "統計"]):
                    title = th_text

            rows = tbl.find_all("tr")
            if len(rows) < 2:
                continue

            headers = []
            data_start = 0
            for i, row in enumerate(rows):
                cells = row.find_all(["th", "td"])
                texts = [c.get_text(strip=True) for c in cells]
                if any(k in " ".join(texts) for k in ["時間", "數據", "參考", "隊伍"]):
                    headers = texts
                    data_start = i + 1
                    if not title:
                        title = texts[0] if texts else ""
                    break

            matches = []
            total = 0
            for row in rows[data_start:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                row_text = " ".join(c.get_text(strip=True) for c in cells)
                if "總場次" in row_text:
                    try:
                        total = int(row_text.split(":")[-1].strip())
                    except Exception:
                        total = 0
                    continue
                if len(cells) < 2:
                    continue
                link_tag = cells[0].find("a")
                matches.append({
                    "team":      link_tag.get_text(strip=True) if link_tag else cells[0].get_text(strip=True),
                    "team_url":  link_tag.get("href", "") if link_tag else "",
                    "cols":      [c.get_text(strip=True) for c in cells],
                    "highlight": _row_highlight(row),
                })

            if matches or total:
                sections.append({
                    "title":   title,
                    "headers": headers,
                    "matches": matches,
                    "total":   total,
                })

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
                logger.info(f"抓取 {name}: {url}")
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(1.5)

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
                logger.error(f"{name} 失敗：{e}")
                result["strategies"][name] = {
                    "error": str(e), "sections": [], "scraped_at": ""
                }

        return result


def _row_highlight(row_tag) -> str:
    bg  = row_tag.get("bgcolor", "").lower()
    cls = " ".join(row_tag.get("class", [])).lower()
    if bg in ("#ffcccc", "red", "#ff9999") or "red" in cls:
        return "danger"
    if bg in ("#ccffcc", "green", "#99ff99") or "green" in cls or "success" in cls:
        return "success"
    if bg in ("#ffffcc", "yellow", "#ffff99") or "yellow" in cls:
        return "warning"
    return ""

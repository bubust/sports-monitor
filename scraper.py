"""
scraper.py — requests 版本（不需要瀏覽器）
"""

import time
import logging
import pyotp
from curl_cffi import requests as cf_requests
from bs4 import BeautifulSoup
from datetime import datetime
import config

logger = logging.getLogger(__name__)


class SportsScraper:
    def __init__(self):
        # impersonate="chrome110" 讓 curl_cffi 模擬真實 Chrome，繞過 Cloudflare
        self.session = cf_requests.Session(impersonate="chrome110")
        self.logged_in = False

    def start(self):
        logger.info("Scraper 已啟動（curl_cffi 模式）")

    def stop(self):
        self.session.close()
        logger.info("Scraper 已關閉")

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
        remaining2 = 30 - (int(time.time()) % 30)
        logger.info(f"TOTP: {code}（剩 {remaining2}s）")
        return code

    # ------------------------------------------------------------------
    # 登入
    # ------------------------------------------------------------------
    def login(self) -> bool:
        logger.info("前往登入頁...")
        try:
            resp = self.session.get(config.BASE_URL, timeout=30)
            soup = BeautifulSoup(resp.content, "lxml")

            # 如果已登入
            if self._is_logged_in(resp.text):
                logger.info("已登入")
                self.logged_in = True
                return True

            # 找 form
            form = soup.find("form")
            if not form:
                logger.error("找不到登入表單")
                return False

            # form action
            action = form.get("action", "").strip()
            if not action:
                action = config.BASE_URL
            elif not action.startswith("http"):
                base = config.BASE_URL.rstrip("/")
                action = base + "/" + action.lstrip("/")
            logger.info(f"Form action: {action}")

            # 收集所有欄位
            data = {}
            for inp in form.find_all("input"):
                name = inp.get("name", "")
                val  = inp.get("value", "")
                if name:
                    data[name] = val

            # 找 text inputs（帳號 / 認證碼）
            text_inputs = form.find_all("input", {"type": ["text", None]})
            text_inputs = [i for i in text_inputs
                           if i.get("type", "text").lower() not in ("hidden", "submit", "button", "checkbox", "radio")]

            # 找 password input
            pw_inputs = form.find_all("input", {"type": "password"})

            logger.info(f"text inputs: {[i.get('name','?') for i in text_inputs]}")
            logger.info(f"pw inputs:   {[i.get('name','?') for i in pw_inputs]}")

            # 填帳號（第1個 text）
            if text_inputs:
                data[text_inputs[0].get("name", "email")] = config.USERNAME
                logger.info(f"填帳號 → {text_inputs[0].get('name')}")

            # 填密碼
            if pw_inputs:
                data[pw_inputs[0].get("name", "password")] = config.PASSWORD
                logger.info(f"填密碼 → {pw_inputs[0].get('name')}")

            # 填認證碼（第2個 text）
            if len(text_inputs) >= 2:
                code = self._totp()
                data[text_inputs[1].get("name", "code")] = code
                logger.info(f"填 TOTP → {text_inputs[1].get('name')}")
            else:
                logger.warning("找不到第2個 text input，TOTP 欄位可能未填")

            # 送出
            logger.info(f"送出登入：{list(data.keys())}")
            resp2 = self.session.post(action, data=data, timeout=30,
                                      allow_redirects=True)
            logger.info(f"登入後 URL: {resp2.url}  狀態: {resp2.status_code}")

            if self._is_logged_in(resp2.text):
                logger.info("登入成功！")
                self.logged_in = True
                return True
            else:
                snippet = resp2.text[:400].replace("\n", " ")
                logger.error(f"登入失敗，回應: {snippet}")
                return False

        except Exception as e:
            logger.error(f"login() 例外：{e}")
            return False

    def _is_logged_in(self, html: str) -> bool:
        fail = ["驗證碼輸入錯誤", "請先登入", "0x403", "0x401"]
        if any(k in html for k in fail):
            return False
        if "會員帳號" in html:
            return False
        return True

    # ------------------------------------------------------------------
    # 解析頁面
    # ------------------------------------------------------------------
    def _parse_html(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
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
            "url":         url,
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
                resp = self.session.get(url, timeout=30)

                # 被登出
                if "請先登入" in resp.text or "會員帳號" in resp.text:
                    self.logged_in = False
                    logger.warning("Session 失效，重新登入...")
                    if not self.login():
                        result["error"] = "重新登入失敗"
                        return result
                    resp = self.session.get(url, timeout=30)

                result["strategies"][name] = self._parse_html(resp.text, url)

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
    if "gray" in bg or "grey" in bg or "gray" in cls:
        return "secondary"
    return ""

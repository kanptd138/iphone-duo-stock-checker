#!/usr/bin/env python3
"""
stock_watch.py — เฝ้าหน้าสินค้า แล้วแจ้งเตือนเมื่อของกลับมามีสต็อก
- เปิดหน้าเว็บด้วย Playwright เหมือนผู้ใช้ปกติ (ไม่กดซื้อ ไม่หลบ CAPTCHA)
- แจ้งเตือนบน macOS + LINE (ถ้าตั้ง LINE_CHANNEL_ACCESS_TOKEN)

ใช้งาน:
  python stock_watch.py --test-notify          # ทดสอบส่งแจ้งเตือน (Mac + LINE)
  python stock_watch.py --once                 # เช็กรอบเดียว (มีหน้าจอ)
  python stock_watch.py --once --headless      # เช็กรอบเดียว (ไม่มีหน้าจอ)
  caffeinate -i python stock_watch.py --headless   # เฝ้าต่อเนื่อง กัน Mac sleep
"""
import asyncio
import json
import os
import random
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

# ================= ตั้งค่า =================
PRODUCTS = [
    {"name": "iPhone Duo - Lazada",
     "url": "https://www.lazada.co.th/products/pre-order-iphone-duo-23-69-i16250067859-s127511251733.html"},
    # {"name": "iPhone Duo - Lazada ร้าน 2", "url": "https://www.lazada.co.th/products/..."},
    # {"name": "iPhone Duo - Shopee", "url": "https://shopee.co.th/..."},
]

# export LINE_CHANNEL_ACCESS_TOKEN="..."  (ห้ามใส่ token ตรงในไฟล์)
LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()

# ปุ่มที่แปลว่า "ซื้อ/จองได้" (มองเห็น + กดได้ = มีของ)
BUY_BUTTON = re.compile(
    r"ซื้อเลย|ซื้อสินค้า|buy now|เพิ่มลงรถเข็น|เพิ่มไปยังรถเข็น|ใส่รถเข็น|add to cart|สั่งจอง|จองเลย|pre-?order",
    re.I,
)
# คำในหน้าเว็บ (ใช้ประกอบ)
OUT_OF_STOCK = ["สินค้าหมด", "หมดสต็อก", "หมดแล้ว", "ไม่มีสินค้า", "sold out", "out of stock",
                "แจ้งเตือนเมื่อมีสินค้า", "notify me"]
IN_STOCK = ["ซื้อสินค้า", "ซื้อเลย", "buy now", "เพิ่มไปยังรถเข็น", "เพิ่มลงรถเข็น", "ใส่รถเข็น", "add to cart"]
BLOCKED = ["captcha", "are you a robot", "ไม่ใช่โปรแกรมอัตโนมัติ"]

INTERVAL = (120, 240)             # วินาที สุ่มระหว่างรอบ (อย่าตั้งถี่กว่านี้มาก)
PROFILE_DIR = ".browser-profile"  # เก็บ cookie/login ไว้ใช้ซ้ำ
# ==========================================


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def notify(msg: str, url: str) -> bool:
    """แจ้งเตือน Mac + LINE คืน True ถ้าส่ง LINE สำเร็จ"""
    log(f"NOTIFY: {msg}")
    safe = msg.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e", f'display notification "{safe}" with title "Stock Watch" sound name "Glass"'],
        check=False,
    )
    if not LINE_TOKEN:
        log("⚠️  LINE_CHANNEL_ACCESS_TOKEN ยังไม่ได้ตั้ง → LINE จะไม่เด้ง")
        return False
    payload = json.dumps({"messages": [{"type": "text", "text": f"{msg}\n{url}"}]}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/broadcast",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            log(f"LINE ส่งแล้ว (HTTP {r.status})")
        return True
    except urllib.error.HTTPError as e:
        log(f"⚠️  LINE error {e.code}: {e.read().decode('utf-8', 'ignore')}")
    except Exception as e:
        log(f"⚠️  LINE error: {e}")
    return False


def classify(text: str, url: str) -> str:
    t, u = text.lower(), url.lower()
    if any(k in u for k in ("captcha", "verify", "/buyer/login")) or any(k in t for k in BLOCKED):
        return "blocked"
    if any(k.lower() in t for k in OUT_OF_STOCK):
        return "out"
    if any(k.lower() in t for k in IN_STOCK):
        return "in"
    return "unknown"


async def check(page, product) -> str:
    try:
        await page.goto(product["url"], wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(5_000)  # รอ JS render ราคา/ปุ่ม

        text_status = classify(await page.inner_text("body"), page.url)
        if text_status == "blocked":
            return "blocked"

        # เช็กจากปุ่มซื้อจริง: มองเห็น + กดได้ + ไม่มี class disabled = มีของ
        btns = page.get_by_role("button", name=BUY_BUTTON)
        for i in range(await btns.count()):
            b = btns.nth(i)
            if await b.is_visible() and await b.is_enabled():
                cls = (await b.get_attribute("class") or "").lower()
                if "disabled" not in cls:
                    return "in"
        return "out" if text_status in ("out", "in") else text_status
    except Exception as e:
        log(f"{product['name']}: error {e}")
        return "error"


async def main() -> None:
    if "--test-notify" in sys.argv:
        ok = notify("🔔 ทดสอบแจ้งเตือน Stock Watch", PRODUCTS[0]["url"])
        sys.exit(0 if ok else 1)

    # import ตรงนี้ เพื่อให้ --test-notify ใช้ได้แม้ยังไม่ได้ลง Playwright
    from playwright.async_api import async_playwright

    once = "--once" in sys.argv
    headless = "--headless" in sys.argv
    last: dict[str, str] = {}

    log(f"เริ่มเฝ้า {len(PRODUCTS)} ลิงก์ ({'headless' if headless else 'มีหน้าจอ'}"
        f"{', ส่ง LINE' if LINE_TOKEN else ', ⚠️ ไม่ส่ง LINE (ไม่มี token)'})")

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=headless,
            channel="chromium" if headless else None,  # headless โหมดใหม่ ใกล้ browser จริงกว่า
            locale="th-TH",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            while True:
                for p in PRODUCTS:
                    status = await check(page, p)
                    log(f"{p['name']}: {status}")
                    if status != last.get(p["url"]):
                        if status == "in":
                            notify(f"🟢 มีของแล้ว: {p['name']}", p["url"])
                        elif status == "blocked":
                            hint = "รันใหม่แบบไม่ใส่ --headless แล้วยืนยันเอง" if headless else "ไปยืนยันในหน้าต่าง browser"
                            notify(f"⚠️ เว็บขอยืนยันตัวตน: {p['name']} — {hint}", p["url"])
                    last[p["url"]] = status
                    await asyncio.sleep(random.uniform(3, 8))
                if once:
                    break
                wait = random.uniform(*INTERVAL)
                if "blocked" in last.values():
                    wait *= 3  # โดนเช็กบอท → ถอยห่างขึ้น
                await asyncio.sleep(wait)
        finally:
            try:
                await ctx.close()
            except Exception:
                pass  # browser ปิดไปแล้วตอนกด Ctrl+C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("หยุดแล้ว")

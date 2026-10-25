#!/usr/bin/env python3
"""
Apple Store (TH) pickup-stock checker — single-pass run, meant to be
triggered on a schedule (e.g. a GitHub Actions cron job every 5 minutes).

Checks every product in config.json against the same JSON endpoint
https://www.apple.com/th/shop/buy-iphone/... itself calls, and notifies via
LINE Messaging API and/or email the moment store pickup becomes available.

Secrets (LINE channel access token, Gmail app password) are read from
environment variables LINE_CHANNEL_ACCESS_TOKEN / GMAIL_APP_PASSWORD so they
never need to live in config.json or in this repo.

Usage: python3 check_stock.py
"""

import json
import logging
import os
import smtplib
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
STATE_PATH = SCRIPT_DIR / "state.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("check_stock")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def check_stock(product: dict) -> dict:
    """Returns {'available': bool, 'store_count': int, 'raw': dict}"""
    country = product["country_path"]
    part = product["part_number"]
    zip_code = product["zip_code"]
    query = urllib.parse.urlencode({"parts.0": part, "location": zip_code})
    url = f"https://www.apple.com/{country}/shop/sba/availability-message?{query}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Referer": urllib.parse.quote(product["product_page_url"], safe=":/"),
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    content = data.get("body", {}).get("content", [])
    if not content:
        raise ValueError(f"unexpected response shape: {data}")
    entry = content[0]
    return {
        "available": bool(entry.get("availableAtAnyStore")),
        "store_count": entry.get("partAvailableStoresCount", 0),
        "raw": entry,
    }


def notify_line(cfg: dict, text: str) -> bool:
    line_cfg = cfg["line"]
    if not line_cfg.get("enabled"):
        return False
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or line_cfg.get("channel_access_token")
    if not token:
        log.error("LINE enabled but no channel access token available (env or config)")
        return False
    url = "https://api.line.me/v2/bot/message/broadcast"
    payload = json.dumps({"messages": [{"type": "text", "text": text}]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        log.info("LINE notification sent")
        return True
    except urllib.error.HTTPError as e:
        log.error("LINE push failed: %s %s", e.code, e.read().decode("utf-8", "ignore"))
    except Exception:
        log.exception("LINE push failed")
    return False


def notify_email(cfg: dict, subject: str, body: str) -> bool:
    email_cfg = cfg["email"]
    if not email_cfg.get("enabled"):
        return False
    app_password = os.environ.get("GMAIL_APP_PASSWORD") or email_cfg.get("app_password")
    if not app_password:
        log.error("Email enabled but no app password available (env or config)")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = email_cfg["from_addr"]
    msg["To"] = email_cfg["to_addr"]
    try:
        with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"], timeout=20) as server:
            server.starttls()
            server.login(email_cfg["from_addr"], app_password)
            server.send_message(msg)
        log.info("Email notification sent")
        return True
    except Exception:
        log.exception("Email send failed")
        return False


def main() -> None:
    cfg = load_config()
    products = cfg["products"]
    state = load_state()
    had_failure = False

    for product in products:
        part = product["part_number"]
        try:
            result = check_stock(product)
            available = result["available"]
            log.info("Check [%s]: available=%s store_count=%s", part, available, result["store_count"])

            if available and not state.get(part, False):
                message = (
                    f"มีสินค้าแล้ว! {product['label']}\n"
                    f"จำนวนร้านที่มีสต็อก: {result['store_count']}\n"
                    f"{product['product_page_url']}"
                )
                log.info("STOCK FOUND [%s] -> notifying", part)
                sent_line = notify_line(cfg, message)
                sent_email = notify_email(cfg, f"[Stock Alert] {product['label']} มีสต็อกแล้ว", message)
                if not (sent_line or sent_email):
                    # Leave state as not-available so the next run retries the alert.
                    log.error("No notification delivered for %s; will retry next run", part)
                    had_failure = True
                    continue

            state[part] = available

        except Exception:
            log.exception("Check failed for %s", part)
            had_failure = True

    save_state(state)
    if had_failure:
        # Non-zero exit marks the GitHub Actions run as failed, which emails the repo owner.
        sys.exit(1)


if __name__ == "__main__":
    main()

# --- Setup notes ---
#
# LINE (LINE Notify was shut down in March 2025 — use the Messaging API instead):
#   1. Create a LINE Official Account at manager.line.biz, then enable
#      Messaging API for it under Settings -> Messaging API (pick an existing
#      Provider so the channel also shows up in developers.line.biz/console).
#   2. In LINE Developers Console, open the channel's "Messaging API" tab,
#      issue a long-lived "Channel access token".
#   3. Scan the channel's QR code with your phone to add the bot as a friend.
#   4. Set line.enabled = true in config.json. Put the token in the
#      LINE_CHANNEL_ACCESS_TOKEN GitHub Actions secret (or env var locally) —
#      never in config.json, since this repo may be pushed to GitHub.
#   Notifications are sent via the broadcast endpoint (reaches all friends of
#   the bot), so no user ID lookup is needed — fine for a personal single-user bot.
#
# Email (Gmail):
#   1. Enable 2-Step Verification on the Google account.
#   2. Create an "App Password" at https://myaccount.google.com/apppasswords.
#   3. Set email.enabled = true in config.json. Put the password in the
#      GMAIL_APP_PASSWORD GitHub Actions secret (or env var locally).

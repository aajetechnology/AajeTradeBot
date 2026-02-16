import os
import time
import requests
import pytz
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Optional: retry config (you can adjust)
MAX_RETRIES = 3
RETRY_DELAY_SEC = 5

def send_telegram_signal(
    symbol: str,
    verdict_text: str,
    price: Union[str, float, None] = None,
    retry_count: int = 0
) -> bool:
    """
    Send trading signal or system message to Telegram.
    Supports normal signals and SYSTEM heartbeats/outcomes.
    
    Returns True if sent successfully, False otherwise.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram credentials missing → message not sent")
        return False

    lagos_tz = pytz.timezone('Africa/Lagos')
    now = datetime.now(lagos_tz)

    if symbol == "SYSTEM":
        # Heartbeat, outcome, error messages – plain text
        text = verdict_text
    else:
        # Trading signal – formatted
        direction = "CALL 🟢" if any(word in verdict_text.upper() for word in ["BUY", "CALL"]) else "PUT 🔴"

        # Extract confidence
        match = re.search(r'(\d{2,3})%', verdict_text)
        confidence = match.group(1) + "%" if match else "—"

        entry_time = now.strftime("%H:%M:%S")
        m1 = (now + timedelta(minutes=2)).strftime("%H:%M")
        m2 = (now + timedelta(minutes=4)).strftime("%H:%M")
        m3 = (now + timedelta(minutes=6)).strftime("%H:%M")

        # Safe price formatting
        if price is None:
            price_str = "—"
        else:
            try:
                price_str = f"{float(price):.5f}"
            except (ValueError, TypeError):
                price_str = str(price)

        text = (
            f"🌟 **AAJE PREMIUM SIGNAL** 🌟\n\n"
            f"📊 **Asset:**   `{symbol}`\n"
            f"💰 **Price:**   `{price_str}`\n"
            f"↕️ **Direction:** `{direction}`\n"
            f"⏰ **Entry:**    `{entry_time}`\n"
            f"⌛ **Expiry:**   `2 min`\n"
            f"🔥 **Confidence:** `{confidence}`\n\n"
            f"🚀 **Martingale levels:**\n"
            f"   1   →  {m1}\n"
            f"   2   →  {m2}\n"
            f"   3   →  {m3}\n\n"
            f"⚠️ Trade 1–2% risk max"
        )

    # Telegram API call with retry
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    for attempt in range(retry_count + 1, MAX_RETRIES + 1):
        try:
            r = requests.post(url, data=payload, timeout=10)
            if r.status_code == 200:
                logger.info(f"Telegram message sent successfully: {symbol} (attempt {attempt})")
                return True
            else:
                logger.warning(f"Telegram failed {r.status_code}: {r.text} (attempt {attempt})")
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram network error (attempt {attempt}): {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SEC)

    logger.error(f"Failed to send Telegram message for {symbol} after {MAX_RETRIES} attempts")
    return False


# Optional: Future extension for sending images/charts (uncomment when needed)
# def send_telegram_photo(photo_url: str, caption: str):
#     token = os.getenv("TELEGRAM_BOT_TOKEN")
#     chat_id = os.getenv("TELEGRAM_CHAT_ID")
#     if not token or not chat_id:
#         return False
#     url = f"https://api.telegram.org/bot{token}/sendPhoto"
#     payload = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
#     files = {"photo": requests.get(photo_url).content}
#     try:
#         r = requests.post(url, data=payload, files=files, timeout=15)
#         return r.status_code == 200
#     except Exception as e:
#         logger.error(f"Telegram photo send failed: {e}")
#         return False
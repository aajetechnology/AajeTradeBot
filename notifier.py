import os
import requests
import pytz
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def send_telegram_signal(symbol: str, verdict_text: str, price: str | float | None = None):
    """
    Send trading signal or system message to Telegram.
    Supports both normal signals and SYSTEM heartbeats/outcomes.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram credentials missing → message not sent")
        return

    lagos_tz = pytz.timezone('Africa/Lagos')
    now = datetime.now(lagos_tz)

    if symbol == "SYSTEM":
        # Heartbeat, outcome, error messages – plain text
        text = verdict_text
    else:
        # Trading signal – formatted
        direction = "CALL 🟢" if "BUY" in verdict_text.upper() or "CALL" in verdict_text.upper() else "PUT 🔴"

        # Try to extract confidence
        import re
        match = re.search(r'(\d{2,3})%', verdict_text)
        confidence = match.group(1) + "%" if match else "—"

        entry_time = now.strftime("%H:%M:%S")
        m1 = (now + timedelta(minutes=2)).strftime("%H:%M")
        m2 = (now + timedelta(minutes=4)).strftime("%H:%M")
        m3 = (now + timedelta(minutes=6)).strftime("%H:%M")

        price_str = f"{float(price):.5f}" if price is not None else "—"

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

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code == 200:
            logger.info(f"Telegram message sent: {symbol}")
        else:
            logger.error(f"Telegram failed {r.status_code}: {r.text}")
    except Exception as e:
        logger.error(f"Telegram network error: {e}")
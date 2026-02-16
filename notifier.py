import os
import requests
import pytz
from datetime import datetime, timedelta

def send_telegram_signal(symbol, verdict_text, price):
    """Formats and sends trading signals or system heartbeats to Telegram."""
    
    # 1. Load Credentials Safely
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("⚠️ Telegram credentials missing. Signal not sent.")
        return

    # 2. Handle System Heartbeats (New Feature)
    # If the symbol is 'SYSTEM', we skip trade formatting and send a plain message.
    if symbol == "SYSTEM":
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id, 
            "text": verdict_text, 
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, data=payload, timeout=10)
            print("📡 Heartbeat sent to Telegram.")
        except Exception as e:
            print(f"❌ Heartbeat failed: {e}")
        return

    # 3. Extract Direction and Confidence for Trades
    direction_raw = "BUY" if "BUY" in verdict_text.upper() else "SELL"
    emoji = "🟢 CALL" if direction_raw == "BUY" else "🔴 PUT"
    
    # Robust Confidence Extraction
    import re
    conf_match = re.search(r'(\d+)%', verdict_text)
    confidence = f"{conf_match.group(1)}%" if conf_match else "85%+"

    # 4. Time Management (Nigeria Time Zone)
    lagos_tz = pytz.timezone('Africa/Lagos')
    now = datetime.now(lagos_tz)
    
    entry_time = now.strftime("%H:%M:%S")
    # Calculating expiry levels for 2-minute Binary Options logic
    m1 = (now + timedelta(minutes=2)).strftime("%H:%M")
    m2 = (now + timedelta(minutes=4)).strftime("%H:%M")
    m3 = (now + timedelta(minutes=6)).strftime("%H:%M")

    # 5. Professional Signal Template
    message = (
        f"🌟 **AAJE AI PREMIUM SIGNAL** 🌟\n\n"
        f"📊 **ASSET:** `{symbol}`\n"
        f"🎯 **PRICE:** `{price}`\n"
        f"↕️ **DIRECTION:** `{emoji}`\n"
        f"⏰ **ENTRY:** `{entry_time}`\n"
        f"⌛ **EXPIRY:** `2 MINUTES`\n"
        f"🔥 **CONFIDENCE:** `{confidence}`\n\n"
        f"🚀 **MARTINGALE STEPS:**\n"
        f"└ 1️⃣ M1: `{m1}`\n"
        f"└ 2️⃣ M2: `{m2}`\n"
        f"└ 3️⃣ M3: `{m3}`\n\n"
        f"⚠️ *Risk Warning: Only trade with 1-3% of your balance.*"
    )

    # 6. Execute Request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": message, 
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            print(f"✅ Signal for {symbol} pushed to Telegram.")
        else:
            print(f"❌ Telegram Error: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"📡 Network Error: {e}")
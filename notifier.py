import os
import requests
import pytz
from datetime import datetime, timedelta

def send_telegram_signal(symbol, verdict_text, price):
    """Formats and sends a high-quality trading signal to Telegram."""
    
    # 1. Load Credentials Safely
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("⚠️ Telegram credentials missing. Signal not sent.")
        return

    # 2. Extract Direction and Confidence
    # Adding emoji support for better user readability
    direction_raw = "BUY" if "BUY" in verdict_text.upper() else "SELL"
    emoji = "🟢 CALL" if direction_raw == "BUY" else "🔴 PUT"
    
    try:
        # Improved parsing to handle different AI response formats
        confidence = verdict_text.split("Confidence:")[1].split("%")[0].strip() + "%"
    except (IndexError, AttributeError):
        confidence = "85%+"

    # 3. Time Management (Nigeria Time Zone)
    lagos_tz = pytz.timezone('Africa/Lagos')
    now = datetime.now(lagos_tz)
    
    entry_time = now.strftime("%H:%M:%S")
    # Calculating expiry levels for 2-minute Binary Options logic
    m1 = (now + timedelta(minutes=2)).strftime("%H:%M")
    m2 = (now + timedelta(minutes=4)).strftime("%H:%M")
    m3 = (now + timedelta(minutes=6)).strftime("%H:%M")

    # 4. Professional Signal Template
    # We use bold and code blocks (backticks) for a premium look
    message = (
        f"🌟 **AAJE AI PREMIUM SIGNAL** 🌟\n\n"
        f"📊 **ASSET:** `{symbol} (OTC)`\n"
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

    # 5. Execute Request with Timeout
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
        print(f"📡 Network Error: Could not reach Telegram: {e}")
import os
import requests
from datetime import datetime, timedelta
import pytz

def send_telegram_signal(symbol, verdict_text, price):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") 
    
    # Parse Verdict (e.g., "Verdict: BUY Confidence: 88%")
    direction = "BUY" if "BUY" in verdict_text.upper() else "SELL"
    confidence = verdict_text.split("Confidence:")[1].strip() if "Confidence:" in verdict_text else "85%"
    
    # Time Management (Nigeria Time)
    lagos_tz = pytz.timezone('Africa/Lagos')
    now = datetime.now(lagos_tz)
    
    entry_window = now.strftime("%I:%M %p")
    l1 = (now + timedelta(minutes=2)).strftime("%I:%M %p")
    l2 = (now + timedelta(minutes=4)).strftime("%I:%M %p")
    l3 = (now + timedelta(minutes=6)).strftime("%I:%M %p")

    # Signal Template
    message = (
        f"🚨 **TRADE NOW!!** 🚨\n"
        f"📊 **{symbol} OTC**\n"
        f"⏱ **Timeframe:** 2-min expiry\n"
        f"🎯 **AI Confidence:** {confidence}\n"
        f"🕙 **Entry Window:** {entry_window}\n"
        f"↕️ **Direction:** {direction}\n\n"
        f"🪜 **Martingale Levels:**\n"
        f"• Level 1 → {l1}\n"
        f"• Level 2 → {l2}\n"
        f"• Level 3 → {l3}"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})
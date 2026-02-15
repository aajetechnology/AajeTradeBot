import time
import os
import threading
from fastapi import FastAPI
from bot_logic import get_market_analysis, get_all_tradable_assets
from notifier import send_telegram_signal

# 1. Create a dummy FastAPI app so Render/Gunicorn stays happy
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "Bot is running"}

def run_scanner():
    """The actual trading bot loop."""
    print("🌍 Scanner Active. Searching for high-confidence trades...")
    
    # It's better to refresh the asset list inside the loop occasionally
    assets = get_all_tradable_assets()

    while True:
        for symbol in assets:
            print(f"🔍 Analyzing {symbol}...")
            verdict, price = get_market_analysis(symbol)
            
            if verdict and "Confidence:" in verdict:
                try:
                    # Extract confidence number
                    conf_val = int(verdict.split("Confidence:")[1].split("%")[0].strip())
                    
                    if conf_val >= 85:
                        print(f"✅ Signal found: {symbol} at {conf_val}%")
                        send_telegram_signal(symbol, verdict, price)
                        time.sleep(30) # Wait after a signal
                except Exception as e:
                    print(f"⚠️ Error parsing verdict: {e}")
            
            # Rate limiting for Twelve Data Free Tier
            time.sleep(12) 

        print("🔄 Cycle complete. Restarting list...")

# 2. Start the scanner in a separate thread so the Web Server can run at the same time
@app.on_event("startup")
def start_bot():
    threading.Thread(target=run_scanner, daemon=True).start()

if __name__ == "__main__":
    # This part runs when you start it on your laptop
    run_scanner()
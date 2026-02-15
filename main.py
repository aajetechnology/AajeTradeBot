import time
import os
from bot_logic import get_market_analysis, get_all_tradable_assets
from notifier import send_telegram_signal

def run_scanner():
    print("🌍 Scanner Active. Searching for high-confidence trades...")
    assets = get_all_tradable_assets()

    while True:
        for symbol in assets:
            verdict, price = get_market_analysis(symbol)
            
            if verdict and "Confidence:" in verdict:
                # Check if confidence is >= 85
                try:
                    conf_val = int(verdict.split("Confidence:")[1].split("%")[0].strip())
                    if conf_val >= 85:
                        print(f"✅ Signal found: {symbol} at {conf_val}%")
                        send_telegram_signal(symbol, verdict, price)
                        time.sleep(30) # Wait after a signal to avoid spam
                except:
                    pass
            
            print(f"😴 Waiting 12s to stay under API limits...")
            time.sleep(12) 

        print("🔄 Cycle complete. Restarting list...")

if __name__ == "__main__":
    run_scanner()
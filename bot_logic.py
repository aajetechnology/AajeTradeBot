import os
import time
import finnhub
import pandas as pd
import pandas_ta as ta
from twelvedata import TDClient
from groq import Groq
from dotenv import load_dotenv
from notifier import send_telegram_signal

load_dotenv()

# Initialize Clients
# Note: Twelve Data SDK uses 'requests' under the hood. 
# We'll use a retry loop to handle the timeout error you saw.
td = TDClient(apikey=os.getenv('TWELVE_DATA_KEY'))
fh_client = finnhub.Client(api_key=os.getenv('FINNHUB_API_KEY'))
groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))

# --- RISK & SESSION TRACKING ---
trade_stats = {"wins": 0, "losses": 0, "start_time": time.time()}
DAILY_LOSS_LIMIT = 5 

def get_all_tradable_assets():
    return ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "EUR/JPY", "BTC/USD", "ETH/USD"]

def get_market_analysis(symbol):
    """Performs analysis with built-in retry logic for timeouts."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 1. Fetch Data (RSI/EMA needs ~100 rows for accuracy)
            ts = td.time_series(symbol=symbol, interval="1min", outputsize=100)
            df = ts.as_pandas()
            
            if df is None or df.empty:
                return None, None

            # 2. Indicators
            df['RSI'] = ta.rsi(df['close'], length=14)
            df['EMA'] = ta.ema(df['close'], length=20)
            last_row = df.dropna().iloc[-1]

            # 3. News (Secondary data, if it fails we still trade)
            try:
                news = fh_client.general_news('forex', min_id=0)
                headline = news[0]['headline'] if news else "Stable Market"
            except:
                headline = "Neutral"

            # 4. AI Decision
            prompt = (f"Asset: {symbol} | Price: {last_row['close']} | RSI: {last_row['RSI']:.2f} | "
                      f"EMA: {'Above' if last_row['close'] > last_row['EMA'] else 'Below'} | "
                      f"News: {headline}. Provide Verdict: [BUY/SELL/WAIT] and Confidence %.")
            
            chat = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                max_tokens=80
            )
            return chat.choices[0].message.content, last_row['close']

        except Exception as e:
            if "timeout" in str(e).lower() and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5
                print(f"🔄 Timeout for {symbol}. Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
                continue
            print(f"⚠️ Analysis Error ({symbol}): {e}")
            return None, None

def run_scanner():
    """Main loop with Heartbeat and Risk Guardrails."""
    print("🚀 Trading Bot Engine Started...")
    
    while True:
        # Reset daily stats
        if time.time() - trade_stats["start_time"] > 86400:
            trade_stats.update({"wins": 0, "losses": 0, "start_time": time.time()})

        if trade_stats["losses"] >= DAILY_LOSS_LIMIT:
            print("🛑 Daily limit reached. Paused for 1 hour.")
            time.sleep(3600)
            continue

        print(f"\n--- 🕒 Scan Start: {time.strftime('%H:%M:%S')} ---")
        
        for symbol in get_all_tradable_assets():
            print(f"🔍 Analyzing {symbol}...")
            verdict, price = get_market_analysis(symbol)
            
            if verdict and "Confidence:" in verdict:
                try:
                    conf = int(verdict.split("Confidence:")[1].split("%")[0].strip())
                    if conf >= 85:
                        print(f"✅ SIGNAL FOUND: {symbol} ({conf}%)")
                        send_telegram_signal(symbol, verdict, price)
                        time.sleep(30) # Prevent multiple signals for same asset
                except Exception as parse_err:
                    print(f"⚙️ Parsing Error: {parse_err}")
            
            # Twelve Data Free Tier: Max 8 requests/min. 
            # 12s sleep per symbol ensures we stay under the limit safely.
            time.sleep(12)
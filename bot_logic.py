import os
import time
import re  # Added for robust AI response parsing
import finnhub
import pandas as pd
import pandas_ta as ta
from twelvedata import TDClient
from groq import Groq
from dotenv import load_dotenv
from notifier import send_telegram_signal

load_dotenv()

# Initialize Clients
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
            # 1. Fetch Data
            ts = td.time_series(symbol=symbol, interval="1min", outputsize=100)
            df = ts.as_pandas()
            
            if df is None or df.empty:
                return None, None

            # 2. Indicators
            df['RSI'] = ta.rsi(df['close'], length=14)
            df['EMA'] = ta.ema(df['close'], length=20)
            last_row = df.dropna().iloc[-1]

            # 3. News 
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
                print(f"🔄 Timeout for {symbol}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"⚠️ Analysis Error ({symbol}): {e}")
            return None, None

def run_scanner():
    """Main loop with Heartbeat and AI-Safe Parsing."""
    print("🚀 Trading Bot Engine Started...")
    
    # Track the best setup found so you know the bot is "thinking"
    hourly_best = {"symbol": "None", "conf": 0}
    last_heartbeat = time.time()
    
    while True:
        # Reset daily stats every 24h
        if time.time() - trade_stats["start_time"] > 86400:
            trade_stats.update({"wins": 0, "losses": 0, "start_time": time.time()})

        # --- NEW: HOURLY HEARTBEAT ---
        # Sends a Telegram update every 60 minutes even if no trade is found
        if time.time() - last_heartbeat > 3600:
            heartbeat_msg = (
                f"📡 **BOT HEARTBEAT**\n"
                f"━━━━━━━━━━━━━━\n"
                f"✅ Status: `Active & Scanning`\n"
                f"🔝 Best Setup this hour: `{hourly_best['symbol']} ({hourly_best['conf']}%)`\n"
                f"🕒 Next update in: `60 mins`"
            )
            # Use your notifier to send a simple text
            send_telegram_signal("SYSTEM", heartbeat_msg, "N/A")
            
            # Reset heartbeat trackers
            last_heartbeat = time.time()
            hourly_best = {"symbol": "None", "conf": 0}

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
                    conf_match = re.search(r'Confidence:\s*[\*]*(\d+)', verdict)
                    if conf_match:
                        conf = int(conf_match.group(1))
                        
                        # Update the hourly best tracker
                        if conf > hourly_best["conf"]:
                            hourly_best = {"symbol": symbol, "conf": conf}

                        if conf >= 85:
                            print(f"✅ SIGNAL FOUND: {symbol} ({conf}%)")
                            send_telegram_signal(symbol, verdict, price)
                            time.sleep(30) 
                        else:
                            print(f"➖ Low confidence ({conf}%) for {symbol}")
                except Exception as parse_err:
                    print(f"⚠️ Parsing Error: {parse_err}")
            
            time.sleep(12)

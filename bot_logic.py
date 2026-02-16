import os
import time
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

import finnhub
import pandas as pd
import pandas_ta as ta
from twelvedata import TDClient
from groq import Groq
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

from notifier import send_telegram_signal

# ─── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    handlers=[logging.FileHandler("bot_logic.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()

# Clients
td_client = TDClient(apikey=os.getenv('TWELVE_DATA_KEY'))
finnhub_client = finnhub.Client(api_key=os.getenv('FINNHUB_API_KEY'))
groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))

# Config
CONF_THRESHOLD    = int(os.getenv('CONF_THRESHOLD', 84))
SCAN_INTERVAL_SEC = int(os.getenv('SCAN_INTERVAL_SEC', 120))  # 2 minutes default
GROQ_MODEL        = os.getenv('GROQ_MODEL', 'mixtral-8x7b-32768')

# State
stats = {"wins": 0, "losses": 0, "start": time.time(), "pending": {}}
hourly_best = {"symbol": "—", "conf": 0}
last_heartbeat = 0.0

def assets():
    """Keep small number while on free tier — add more after upgrade"""
    return [
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "BTC/USD",
        "ETH/USD",
        # "AUD/USD",
        # "USD/CAD",
        # "EUR/GBP",
        # "EUR/JPY",
        "GBP/JPY"
    ]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=15, max=60))
def get_decision(symbol: str) -> Tuple[Optional[dict], Optional[float]]:
    """Fetch data, compute indicators, ask Groq — with safe column handling"""
    logger.info(f"Analyzing {symbol}")

    # 1. Time series data (this is the credit-consuming call)
    try:
        ts = td_client.time_series(symbol=symbol, interval="1min", outputsize=180)
        df = ts.as_pandas()
        if df is None or len(df) < 60:
            logger.warning(f"Insufficient data for {symbol}")
            return None, None
    except Exception as e:
        err_str = str(e).lower()
        if "api credits" in err_str or "out of api credits" in err_str or "429" in err_str or "limit being 8" in err_str:
            logger.warning(f"Twelve Data RATE LIMIT → sleeping 90s to reset minute...")
            time.sleep(90)
            raise  # let tenacity retry
        else:
            logger.warning(f"Twelve Data fetch failed {symbol}: {e}")
            return None, None

    # 2. Technical indicators
    df.ta.rsi(length=14, append=True)
    df.ta.ema(length=20, append=True)
    df.ta.macd(append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.adx(append=True)

    row = df.iloc[-1]

    # Safe column access with fallbacks
    def safe_float(col: str, fallback=float('nan')) -> float:
        return float(row[col]) if col in row else fallback

    ind = {
        "price": safe_float("close"),
        "rsi": safe_float("RSI_14"),
        "ema20": safe_float("EMA_20"),
        "macd": safe_float("MACD_12_26_9"),
        "macd_sig": safe_float("MACDs_12_26_9"),
        "bb_upper": safe_float("BBU_20_2.0") or safe_float("BBU_20_2", float('nan')),
        "bb_lower": safe_float("BBL_20_2.0") or safe_float("BBL_20_2", float('nan')),
        "adx": safe_float("ADX_14"),
    }

    # Optional: uncomment once to see actual column names in your environment
    # logger.info(f"TA columns for {symbol}: {list(df.columns)}")

    # 3. News from Finnhub (cheap & generous limit)
    try:
        category = 'crypto' if 'USD' in symbol and any(c in symbol for c in ['BTC','ETH']) else 'forex'
        news = finnhub_client.general_news(category, min_id=0)
        headline = news[0]["headline"][:140] if news else "—"
    except:
        headline = "—"

    # 4. Structured prompt for Groq
    prompt = f"""Binary options analyst (2 min expiry).
Data for {symbol}:

Price     : {ind['price']:.5f}
RSI(14)   : {ind['rsi']:.1f}
vs EMA20  : {'above' if ind['price'] > ind['ema20'] else 'below'}
MACD      : {ind['macd']:.4f}  (sig {ind['macd_sig']:.4f})
ADX(14)   : {ind['adx']:.1f}
BBands    : {'upper' if ind['price'] > ind['bb_upper']*0.98 else 'lower' if ind['price'] < ind['bb_lower']*1.02 else 'middle'}
News      : {headline}

Respond ONLY with valid JSON:

{{
  "verdict": "BUY"|"SELL"|"WAIT",
  "confidence": 50-100,
  "reason": "short explanation max 70 chars"
}}
"""

    try:
        resp = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_tokens=140
        )
        text = resp.choices[0].message.content.strip()
        data = json.loads(text)
        return data, ind["price"]
    except Exception as e:
        logger.error(f"Groq / parse error {symbol}: {e}")
        return None, None


def check_outcome(signal_id: str):
    if signal_id not in stats["pending"]:
        return

    item = stats["pending"].pop(signal_id)
    symbol = item["symbol"]
    direction = item["dir"]
    entry = item["price"]

    try:
        ts = td_client.time_series(symbol=symbol, interval="1min", outputsize=1)
        df = ts.as_pandas()
        if df.empty:
            return
        exit_price = float(df.iloc[-1]["close"])

        won = (direction == "BUY" and exit_price > entry) or \
              (direction == "SELL" and exit_price < entry)

        if won:
            stats["wins"] += 1
            tag = "✅ WIN"
        else:
            stats["losses"] += 1
            tag = "❌ LOSS"

        msg = (
            f"**SIGNAL RESULT** {tag}\n"
            f"{symbol} {direction} @ {entry:.5f}\n"
            f"Exit: {exit_price:.5f}\n"
            f"W/L: {stats['wins']}–{stats['losses']}"
        )
        send_telegram_signal("SYSTEM", msg)

    except Exception as e:
        logger.error(f"Outcome check failed {symbol}: {e}")


def analyze_one(symbol: str):
    global hourly_best

    decision, price = get_decision(symbol)
    if not decision or decision["verdict"] == "WAIT":
        return

    conf = decision.get("confidence", 0)
    dir_ = decision["verdict"]

    if conf > hourly_best["conf"]:
        hourly_best.update({"symbol": symbol, "conf": conf})

    if conf < CONF_THRESHOLD:
        return

    reason = decision.get("reason", "AI signal")
    text = f"{dir_}  {conf}%  – {reason}"
    send_telegram_signal(symbol, text, price)

    # Schedule outcome check (~2.75 min later)
    sid = f"{symbol}_{int(time.time())}"
    stats["pending"][sid] = {"symbol": symbol, "dir": dir_, "price": price}
    threading.Timer(165, check_outcome, args=(sid,)).start()

    logger.info(f"Signal sent → {symbol} {dir_} @ {conf}%")


def heartbeat():
    global last_heartbeat, hourly_best
    msg = (
        f"**HEARTBEAT** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Status: active\n"
        f"Best this hour: {hourly_best['symbol']} ({hourly_best['conf']}%)\n"
        f"W/L: {stats['wins']} – {stats['losses']}"
    )
    send_telegram_signal("SYSTEM", msg)

    hourly_best = {"symbol": "—", "conf": 0}
    last_heartbeat = time.time()


def run_scanner():
    logger.info("Scanner engine started 🚀 (free-tier safe mode)")

    while True:
        now = time.time()

        # Daily reset
        if now - stats["start"] > 86400:
            stats.update({"wins": 0, "losses": 0, "start": now})
            logger.info("Daily stats reset")

        # Loss limit pause
        if stats["losses"] >= 6:
            logger.warning("Loss limit reached → pausing 60 min")
            time.sleep(3600)
            continue

        # Heartbeat ~every 59 min
        if now - last_heartbeat > 3540:
            heartbeat()

        logger.info(f"Starting scan round ─ {datetime.now().strftime('%H:%M:%S')}")

        for sym in assets():
            logger.info(f"→ {sym}")
            analyze_one(sym)
            time.sleep(15.0)          # Critical: keeps us under 8 credits/min

        logger.info(f"Round finished ─ sleeping {SCAN_INTERVAL_SEC} seconds")
        time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        run_scanner()
    except KeyboardInterrupt:
        logger.info("Scanner stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error in scanner: {e}", exc_info=True)
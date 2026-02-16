import os
import time
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
import threading
import pytz
import yfinance as yf

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

# ─── Config ───────────────────────────────────────────────────────────────────
CONF_THRESHOLD_BASE = int(os.getenv('CONF_THRESHOLD', 82))
MIN_CONF_FOR_SIGNAL = 74
SCAN_INTERVAL_SEC = int(os.getenv('SCAN_INTERVAL_SEC', 240))
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.1-70b-versatile')
MAX_DAILY_CREDITS = 780
CREDITS_WARNING_THRESHOLD = 650

# ─── State ────────────────────────────────────────────────────────────────────
stats = {"wins": 0, "losses": 0, "start": time.time(), "pending": {}}
hourly_best = {"symbol": "—", "conf": 0}
last_heartbeat = 0.0
daily_credits_used = 0
recent_win_rate = 0.50

def assets():
    return [
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "AUD/USD",
        "BTC/USD",
        "ETH/USD"
    ]

def get_finnhub_symbol(symbol: str) -> str:
    if '/' in symbol and 'BTC' not in symbol and 'ETH' not in symbol:
        return 'OANDA:' + symbol.replace('/', '_')
    return 'BINANCE:' + symbol.replace('/', '')

@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=25, max=120))
def get_decision(symbol: str) -> Tuple[Optional[dict], Optional[float]]:
    global daily_credits_used

    logger.info(f"Analyzing {symbol}")

    df = None
    price = None
    source = "unknown"

    # 1. Twelve Data (primary)
    try:
        ts = td_client.time_series(symbol=symbol, interval="1min", outputsize=200)
        df = ts.as_pandas()
        if df is not None and len(df) >= 70:
            source = "TwelveData"
            daily_credits_used += 1
            price = float(df.iloc[-1]['close'])
            logger.info(f"TwelveData success: price = {price}")
    except Exception as e:
        err = str(e).lower()
        if any(x in err for x in ["credits", "limit", "429", "daily"]):
            logger.warning("TwelveData LIMIT → trying Finnhub...")
        else:
            logger.warning(f"TwelveData error: {e}")

    # 2. Finnhub quote fallback
    if price is None:
        try:
            fh_symbol = get_finnhub_symbol(symbol)
            quote = finnhub_client.quote(fh_symbol)
            price = quote.get('c')
            if price is not None and price > 0:
                source = "Finnhub"
                logger.info(f"Finnhub success: price = {price}")
        except Exception as e:
            logger.debug(f"Finnhub failed: {e}")

    # 3. yfinance ultimate fallback
    if price is None:
        try:
            yf_symbol = symbol.replace('/', '') + '=X' if '/' in symbol else symbol + '-USD'
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="5d", interval="1m")
            if not hist.empty:
                df = hist[['Open', 'High', 'Low', 'Close', 'Volume']].rename(
                    columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}
                )
                price = float(df.iloc[-1]['close'])
                source = "yfinance"
                logger.info(f"yfinance success: price = {price}")
            else:
                raise ValueError("No yfinance data")
        except Exception as e:
            logger.error(f"yfinance failed: {e}")

    if price is None:
        logger.warning(f"No price from any source for {symbol}")
        return None, None

    # ─── Indicators (full mode) ──────────────────────────────────────────────
    ind = {"price": price}

    if df is not None and len(df) >= 70:
        df.ta.rsi(length=14, append=True)
        df.ta.ema(length=20, append=True)
        df.ta.macd(append=True)
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.adx(append=True)

        row = df.iloc[-1]

        def safe_float(col: str, fallback=float('nan')) -> float:
            return float(row[col]) if col in row else fallback

        ind.update({
            "rsi": safe_float("RSI_14"),
            "ema20": safe_float("EMA_20"),
            "macd": safe_float("MACD_12_26_9"),
            "macd_sig": safe_float("MACDs_12_26_9"),
            "bb_upper": safe_float("BBU_20_2.0") or safe_float("BBU_20_2", float('nan')),
            "bb_lower": safe_float("BBL_20_2.0") or safe_float("BBL_20_2", float('nan')),
            "adx": safe_float("ADX_14"),
        })
    else:
        logger.info(f"Limited mode for {symbol} – price + news only")
        ind.update({
            "rsi": float('nan'), "ema20": float('nan'), "macd": float('nan'),
            "macd_sig": float('nan'), "bb_upper": float('nan'), "bb_lower": float('nan'),
            "adx": float('nan'),
        })

    # ─── News ────────────────────────────────────────────────────────────────
    news_text = "No news available"
    try:
        cat = 'crypto' if any(c in symbol for c in ['BTC','ETH']) else 'forex'
        news = finnhub_client.general_news(cat, min_id=0)
        headlines = [n["headline"][:120] for n in news[:5]] if news else ["Stable market"]
        news_text = " | ".join(headlines)
    except:
        pass

    # ─── Safe formatted values for prompt ────────────────────────────────────
    rsi_fmt = f"{ind['rsi']:.1f}" if not pd.isna(ind['rsi']) else 'N/A'
    ema_fmt = 'above (bullish)' if not pd.isna(ind['ema20']) and ind['price'] > ind['ema20'] else \
              'below (bearish)' if not pd.isna(ind['ema20']) else 'N/A'
    macd_fmt = f"{ind['macd']:.4f}" if not pd.isna(ind['macd']) else 'N/A'
    macd_sig_fmt = f"{ind['macd_sig']:.4f}" if not pd.isna(ind['macd_sig']) else 'N/A'
    adx_fmt = f"{ind['adx']:.1f}" if not pd.isna(ind['adx']) else 'N/A'
    bb_fmt = 'near upper' if not pd.isna(ind['bb_upper']) and ind['price'] > ind['bb_upper']*0.98 else \
             'near lower' if not pd.isna(ind['bb_lower']) and ind['price'] < ind['bb_lower']*1.02 else \
             'inside bands' if not pd.isna(ind['bb_upper']) else 'N/A'

    limited_note = "Note: Limited mode (API quota) – price + news only." if source != "TwelveData" else ""

    prompt = f"""You are a high-conviction 2-minute binary options trader.

Data for {symbol}:
Price     : {ind['price']:.5f}
RSI(14)   : {rsi_fmt}
vs EMA20  : {ema_fmt}
MACD      : {macd_fmt} (sig {macd_sig_fmt})
ADX(14)   : {adx_fmt}
BBands    : {bb_fmt}
News      : {news_text}

{limited_note}

Be decisive but realistic in limited mode. Use news and price heavily.
Prefer BUY/SELL on strong clues. Use WAIT if uncertain.

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
            temperature=0.2,
            max_tokens=140
        )
        text = resp.choices[0].message.content.strip()
        data = json.loads(text)
        logger.info(f"AI decision {symbol} (source: {source}): {data}")
        return data, ind["price"]
    except Exception as e:
        logger.error(f"Groq error {symbol}: {e}")
        return None, None

def check_outcome(signal_id: str):
    if signal_id not in stats["pending"]:
        return

    item = stats["pending"].pop(signal_id)
    symbol = item["symbol"]
    direction = item["dir"]
    entry = item["price"]

    try:
        fh_symbol = get_finnhub_symbol(symbol)
        quote = finnhub_client.quote(fh_symbol)
        exit_price = quote.get('c')
        if not exit_price or exit_price == 0:
            raise ValueError("No valid quote")

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
            f"Current W/L: {stats['wins']}–{stats['losses']}"
        )
        send_telegram_signal("SYSTEM", msg, None)

        global recent_win_rate
        recent_win_rate = recent_win_rate * 0.65 + (1 if won else 0) * 0.35

    except Exception as e:
        logger.error(f"Outcome check failed {symbol}: {e}")

def analyze_one(symbol: str):
    global hourly_best

    decision, price = get_decision(symbol)
    if not decision or decision["verdict"] == "WAIT":
        return

    conf = decision.get("confidence", 0)
    dir_ = decision["verdict"]

    effective_threshold = CONF_THRESHOLD_BASE
    if recent_win_rate > 0.60:
        effective_threshold = max(72, CONF_THRESHOLD_BASE - 6)
    elif recent_win_rate < 0.45:
        effective_threshold = min(88, CONF_THRESHOLD_BASE + 4)

    if conf > hourly_best["conf"]:
        hourly_best.update({"symbol": symbol, "conf": conf})

    if conf < effective_threshold:
        logger.info(f"Skipped {symbol} – conf {conf}% < {effective_threshold}%")
        return

    reason = decision.get("reason", "AI signal")
    text = f"{dir_} {conf}% – {reason} (threshold: {effective_threshold}%)"
    send_telegram_signal(symbol, text, price)

    sid = f"{symbol}_{int(time.time())}"
    stats["pending"][sid] = {"symbol": symbol, "dir": dir_, "price": price}
    threading.Timer(165, check_outcome, args=(sid,)).start()

    logger.info(f"SIGNAL SENT → {symbol} {dir_} @ {conf}%")

def heartbeat():
    global last_heartbeat, hourly_best
    msg = (
        f"**HEARTBEAT** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Status: active\n"
        f"Best this hour: {hourly_best['symbol']} ({hourly_best['conf']}%)\n"
        f"Recent win rate: {recent_win_rate*100:.1f}%\n"
        f"Daily credits used: {daily_credits_used}/{MAX_DAILY_CREDITS}\n"
        f"W/L: {stats['wins']} – {stats['losses']}"
    )
    send_telegram_signal("SYSTEM", msg, None)

    hourly_best = {"symbol": "—", "conf": 0}
    last_heartbeat = time.time()

def run_scanner():
    global daily_credits_used

    logger.info("Scanner engine started 🚀 (free-tier safe + profitable mode)")

    while True:
        now = time.time()

        if now - stats["start"] > 86400:
            stats.update({"wins": 0, "losses": 0, "start": now})
            daily_credits_used = 0
            logger.info("Daily stats & credits reset")

        if stats["losses"] >= 6:
            logger.warning("Loss limit reached → pause 60 min")
            time.sleep(3600)
            continue

        if now - last_heartbeat > 3540:
            heartbeat()

        logger.info(f"Starting scan round ─ {datetime.now().strftime('%H:%M:%S')}")

        for sym in assets():
            logger.info(f"→ {sym}")
            analyze_one(sym)
            time.sleep(30.0)

            if daily_credits_used >= CREDITS_WARNING_THRESHOLD:
                logger.warning(f"Approaching limit ({daily_credits_used}/{MAX_DAILY_CREDITS})")
                alert_msg = f"⚠️ Credit alert: {daily_credits_used}/{MAX_DAILY_CREDITS} used. Pause at 780."
                send_telegram_signal("SYSTEM", alert_msg, None)

            if daily_credits_used >= MAX_DAILY_CREDITS - 20:
                logger.warning(f"CRITICAL: {daily_credits_used} used → pausing until reset")
                utc_now = datetime.now(timezone.utc)
                next_reset = (utc_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                sleep_sec = (next_reset - utc_now).total_seconds()
                time.sleep(sleep_sec)
                daily_credits_used = 0

        logger.info(f"Round finished ─ sleeping {SCAN_INTERVAL_SEC} seconds")
        time.sleep(SCAN_INTERVAL_SEC)

if __name__ == "__main__":
    try:
        run_scanner()
    except KeyboardInterrupt:
        logger.info("Scanner stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
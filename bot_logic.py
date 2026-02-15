import os
import finnhub
import pandas as pd
import pandas_ta as ta
from twelvedata import TDClient
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# Initialize Clients
td = TDClient(apikey=os.getenv('TWELVE_DATA_KEY'))
fh_client = finnhub.Client(api_key=os.getenv('FINNHUB_API_KEY'))
groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))

def get_all_tradable_assets():
    """Returns the best pairs for IQ Option trading."""
    # We use a curated list to avoid 'Exotic' pairs that waste API credits
    return [
        "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "EUR/JPY", 
        "USD/CAD", "BTC/USD", "ETH/USD", "USD/MXN", "USD/SGD"
    ]

def get_market_analysis(symbol):
    """Analyzes market data and news using local calculation and Groq AI."""
    try:
        # 1. Fetch Price Data (1 credit)
        ts = td.time_series(symbol=symbol, interval="1min", outputsize=100)
        df = ts.as_pandas()

        # 2. Local Math (Free)
        # We use a 14-period RSI and 20-period EMA
        df['RSI'] = ta.rsi(df['close'], length=14)
        df['EMA'] = ta.ema(df['close'], length=20)
        
        # Clean the data (remove the first empty rows)
        df = df.dropna()
        
        # Get the VERY LATEST data point
        last_row = df.iloc[-1] 

        # 3. News Sentiment
        news = fh_client.general_news('forex', min_id=0)
        headline = news[0]['headline'] if news else "Market stable, no major news."

        # 4. Groq AI Decision
        prompt = f"""
        Asset: {symbol}
        Current Price: {last_row['close']}
        Technical Data: RSI is {last_row['RSI']:.2f}, Price is {'above' if last_row['close'] > last_row['EMA'] else 'below'} the 20-EMA.
        Global News: {headline}
        
        You are a pro binary options trader. Based on this, is there a high-probability 2-minute trade?
        Output ONLY in this exact format:
        Verdict: [BUY/SELL/WAIT]
        Confidence: [Percentage]%
        """

        chat = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
        )
        
        analysis_result = chat.choices[0].message.content
        return analysis_result, last_row['close']
        
    except Exception as e:
        print(f"⚠️ Analysis Error for {symbol}: {e}")
        return None, None
import threading
import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from bot_logic import run_scanner

# --- LIFESPAN MANAGER ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This runs when the server starts
    print("🚀 Web server online. Starting Trading Bot thread...")
    bot_thread = threading.Thread(target=run_scanner, daemon=True)
    bot_thread.start()
    yield
    # This runs when the server shuts down
    print("🛑 Shutting down...")

app = FastAPI(lifespan=lifespan)

@app.get("/")
def health_check():
    """Render hits this endpoint to verify the app is live."""
    return {
        "status": "Bot is active",
        "timestamp": time.time(),
        "info": "AajeTradeBot v1.0 Production"
    }

if __name__ == "__main__":
    # This allows you to run locally with 'python main.py'
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
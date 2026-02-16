import threading
import os
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from bot_logic import run_scanner

# ─── Logging setup ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─── Lifespan ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Web server starting. Launching scanner in background…")

    def delayed_bot_start():
        time.sleep(4)           # Give Render time to detect port
        logger.info("Starting trading scanner thread…")
        run_scanner()

    thread = threading.Thread(target=delayed_bot_start, daemon=True)
    thread.start()

    yield

    logger.info("Web server shutting down…")


app = FastAPI(lifespan=lifespan, title="AajeTrade Signal Bot")

@app.get("/")
@app.head("/")
def health():
    """Render health check endpoint"""
    return {
        "status": "running",
        "service": "AajeTradeBot",
        "version": "1.1",
        "timestamp": time.time()
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False
    )
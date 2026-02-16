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

# ─── Lifespan manager ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Web server starting. Launching scanner in background…")

    def delayed_bot_start():
        # Give Render time to detect the port and mark service healthy
        time.sleep(3)
        logger.info("Starting trading scanner thread…")
        try:
            run_scanner()
        except Exception as e:
            logger.critical(f"Scanner thread crashed: {e}", exc_info=True)

    # Launch scanner in background thread (daemon so it stops when app does)
    thread = threading.Thread(target=delayed_bot_start, daemon=True)
    thread.start()

    yield  # Application is running here

    logger.info("Web server shutting down…")

# ─── FastAPI application ─────────────────────────────────────────────────────
app = FastAPI(lifespan=lifespan, title="AajeTrade Signal Bot")

@app.get("/")
@app.head("/")
def health():
    """Render health check endpoint – must return 200 OK quickly"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "service": "AajeTradeBot"
    }

if __name__ == "__main__":
    # Render provides PORT via environment variable (usually 10000)
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting uvicorn server on 0.0.0.0:{port}")

    uvicorn.run(
        "main:app",                    # Correct module:app reference
        host="0.0.0.0",
        port=port,
        log_level="info",
        workers=1,                     # Critical: single worker prevents port conflicts
        reload=False,
        timeout_keep_alive=30,         # Helps with long-running background tasks
        timeout_graceful_shutdown=10   # Clean shutdown on Render SIGTERM
    )
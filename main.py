import threading
import os
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from bot_logic import run_scanner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Web server starting. Launching scanner in background…")

    def delayed_bot_start():
        time.sleep(3)  # Short delay to let Render detect port first
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
    return {"status": "healthy", "timestamp": time.time()}

if __name__ == "__main__":
    # Render provides PORT via env var
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Binding FastAPI/Uvicorn to 0.0.0.0:{port}")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        workers=1,           # Single worker – very important on Render free tier
        reload=False
    )
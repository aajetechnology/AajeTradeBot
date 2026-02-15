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
    """
    Handles startup and shutdown. 
    We start the bot logic in a separate thread so it doesn't block the web server.
    """
    print("🌐 [Web Server] Online. Preparing to start bot...")
    
    # We define a small wrapper to allow the web server to bind to the port first
    def start_bot_with_delay():
        time.sleep(5) # 5-second delay to ensure Render detects the open port
        print("🤖 [Bot Engine] Initializing scanner thread...")
        run_scanner()

    bot_thread = threading.Thread(target=start_bot_with_delay, daemon=True)
    bot_thread.start()
    
    yield
    print("🛑 [System] Shutting down...")

# Initialize FastAPI with lifespan
app = FastAPI(lifespan=lifespan)

@app.get("/")
@app.head("/") # Render specifically pings the root with HEAD/GET to check health
def health_check():
    """
    Crucial for Render. This endpoint must return 200 OK 
    for the deployment to be marked as 'Live'.
    """
    return {
        "status": "Bot is active",
        "timestamp": time.time(),
        "info": "AajeTradeBot v1.0 Production"
    }

if __name__ == "__main__":
    # Get port from environment (Render sets this automatically)
    port = int(os.environ.get("PORT", 10000))
    # Bind to 0.0.0.0 so the external world (and Render) can see the app
    uvicorn.run(app, host="0.0.0.0", port=port)
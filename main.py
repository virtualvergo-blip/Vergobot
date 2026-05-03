"""
main.py
Entry point for the Meme Coin AI Agent
"""
import asyncio
import os
import signal
from dotenv import load_dotenv
load_dotenv()

from database.db_manager import init_db
from agents.channel_listener import create_client, start_listener, SIGNAL_CHANNELS, API_ID, API_HASH, PHONE
from agents.bot_commands import start_polling
from agents.notifier import send_startup_message, send_error_alert
from agents.token_monitor import stop_all


async def health_check_server():
    """Simple HTTP health check for Railway"""
    from aiohttp import web
    
    async def health(request):
        from database.db_manager import get_winrate_stats
        from agents.token_monitor import get_active_count
        stats = await get_winrate_stats()
        return web.json_response({
            "status": "ok",
            "tokens_in_db": stats["total_tokens"],
            "active_monitors": get_active_count(),
            "winrate": stats["winrate_pct"]
        })
    
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[Health] Server running on port {port}")


async def main():
    print("=" * 50)
    print("🤖 MEME COIN AI AGENT STARTING")
    print("=" * 50)
    
    # Initialize database
    await init_db()
    print("[Main] Database initialized")
    
    # Validate configuration
    if not API_ID or not API_HASH:
        raise ValueError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required!")
    
    if not os.getenv("GROQ_API_KEY"):
        raise ValueError("GROQ_API_KEY is required! Get it free at https://console.groq.com")
    
    if not SIGNAL_CHANNELS:
        print("[Main] WARNING: No SIGNAL_CHANNELS configured!")
    
    # Create Telethon client
    client = await create_client()
    
    # Register message handlers
    await start_listener(client)
    
    # Start the client
    SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "")
    if SESSION_STRING:
        # Di Railway/server: gunakan connect() + validasi session.
        # JANGAN pakai client.start() tanpa phone — jika session expired
        # Telethon akan minta input interaktif yang crash di environment tanpa terminal.
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError(
                "TELEGRAM_SESSION_STRING tidak valid atau sudah expired!\n"
                "Jalankan generate_session.py di lokal untuk generate session baru,\n"
                "lalu update env var TELEGRAM_SESSION_STRING di Railway."
            )
    else:
        # Lokal: login interaktif via nomor HP
        await client.start(phone=PHONE)
    
    print("[Main] Telegram client connected")
    
    # Start health check server (required for Railway)
    await health_check_server()
    
    # Start bot command polling in background
    bot_task = asyncio.create_task(start_polling())
    
    # Send startup message
    await send_startup_message(SIGNAL_CHANNELS)
    
    print("[Main] ✅ All systems running!")
    print(f"[Main] Monitoring channels: {', '.join(SIGNAL_CHANNELS)}")
    
    # Handle graceful shutdown
    shutdown_event = asyncio.Event()
    
    def handle_shutdown(sig, frame):
        print(f"\n[Main] Received {sig}. Shutting down...")
        shutdown_event.set()
    
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        # Run until shutdown
        await asyncio.gather(
            client.run_until_disconnected(),
            shutdown_event.wait(),
            return_exceptions=True
        )
    finally:
        print("[Main] Stopping all monitors...")
        await stop_all()
        bot_task.cancel()
        await client.disconnect()
        print("[Main] 👋 Agent stopped")


if __name__ == "__main__":
    asyncio.run(main())

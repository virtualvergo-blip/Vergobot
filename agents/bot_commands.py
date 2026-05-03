"""
agents/bot_commands.py
Handles Telegram bot commands from the user
"""
import os
import asyncio
import aiohttp
import json
from datetime import datetime, timezone
from database.db_manager import get_winrate_stats, get_recent_tokens
from agents.token_monitor import get_active_count, active_monitors
from agents.notifier import send_status_message, _send_message

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
YOUR_CHAT_ID = str(os.getenv("YOUR_CHAT_ID", ""))

HELP_TEXT = """🤖 <b>MEME AGENT COMMANDS</b>

/status — Agent stats, winrate, DB size
/tokens — Last 10 scanned tokens  
/active — Currently monitoring tokens
/help — This message

<i>Agent auto-notifies on every call from signal channels.</i>"""


async def handle_update(update: dict):
    """Process incoming Telegram bot update"""
    message = update.get("message", {})
    if not message:
        return
    
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "")
    
    # Security: only respond to owner
    if chat_id != YOUR_CHAT_ID:
        return
    
    if not text.startswith("/"):
        return
    
    command = text.split()[0].lower()
    
    if command == "/status":
        stats = await get_winrate_stats()
        active_count = get_active_count()
        await send_status_message(stats, active_count)
    
    elif command == "/tokens":
        tokens = await get_recent_tokens(limit=10)
        if not tokens:
            await _send_message("📭 No tokens in database yet.")
            return
        
        lines = ["📋 <b>RECENT TOKENS</b>\n"]
        for i, t in enumerate(tokens, 1):
            pred = t.get("last_prediction", "—")
            conf = t.get("last_confidence", 0)
            conf_pct = f"{round((conf or 0) * 100)}%" if conf else "—"
            lines.append(
                f"{i}. <b>{t.get('symbol', '?')}</b> [{t.get('chain', '?').upper()}]\n"
                f"   Prediction: {pred} ({conf_pct})\n"
                f"   Seen: {t.get('first_seen_at', '?')[:16]}\n"
            )
        
        await _send_message("\n".join(lines))
    
    elif command == "/active":
        if not active_monitors:
            await _send_message("😴 No tokens currently being monitored.")
            return
        
        lines = [f"🔴 <b>ACTIVE MONITORS ({len(active_monitors)})</b>\n"]
        for addr, info in active_monitors.items():
            elapsed = (datetime.now(timezone.utc) - info["start_time"]).seconds // 60
            lines.append(
                f"• <b>{info.get('symbol', addr[:8])}</b>\n"
                f"  Running: {elapsed}m | Snapshots: {info.get('snapshots', 0)}\n"
            )
        
        await _send_message("\n".join(lines))
    
    elif command == "/help":
        await _send_message(HELP_TEXT)


async def start_polling():
    """Start bot polling for commands"""
    if not BOT_TOKEN:
        print("[Bot] No BOT_TOKEN configured, commands disabled")
        return
    
    offset = 0
    url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    
    print("[Bot] Starting command polling...")
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(
                    f"{url}/getUpdates",
                    params={"offset": offset, "timeout": 30, "limit": 10},
                    timeout=aiohttp.ClientTimeout(total=35)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        updates = data.get("result", [])
                        
                        for update in updates:
                            offset = update["update_id"] + 1
                            try:
                                await handle_update(update)
                            except Exception as e:
                                print(f"[Bot] Update handler error: {e}")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Bot] Polling error: {e}")
                await asyncio.sleep(5)

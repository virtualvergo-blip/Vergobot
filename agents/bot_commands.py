"""
agents/bot_commands.py
Telegram bot command handler via Bot API polling.
"""
import os
import asyncio
import aiohttp
from database.db_manager import get_winrate_stats, get_recent_tokens
from agents.token_monitor import active_monitors
from agents.notifier import send_status_message

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

async def start_polling():
    """Start bot command polling via Telegram Bot API."""
    if not BOT_TOKEN:
        print("[Bot] No BOT_TOKEN configured, skipping command polling")
        return

    print("[Bot] Starting command polling...")
    offset = 0

    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&limit=10"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        await asyncio.sleep(5)
                        continue

                    data = await resp.json()
                    if not data.get("ok"):
                        await asyncio.sleep(5)
                        continue

                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        await _handle_update(update)

        except Exception as e:
            print(f"[Bot] Polling error: {e}")
            await asyncio.sleep(5)

async def _handle_update(update: dict):
    """Handle a single update from Bot API."""
    message = update.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")

    if not text or not chat_id:
        return

    if text.startswith("/status"):
        stats = await get_winrate_stats()
        from agents.token_monitor import get_active_count
        await send_status_message(stats, get_active_count())

    elif text.startswith("/tokens"):
        tokens = await get_recent_tokens(10)
        msg = "📊 <b>Recent Tokens:</b>\n\n"
        for t in tokens:
            sym = t.get('symbol', '?')
            ca = t.get('contract_address', '?')
            pred = t.get('last_prediction', 'N/A')
            conf = t.get('last_confidence', 0)
            conf_str = f"{conf*100:.0f}%" if conf else "N/A"
            msg += f"• <b>{sym}</b> | <code>{ca[:10]}...</code> | {pred} ({conf_str})\n"
        await _send_bot_message(chat_id, msg)

    elif text.startswith("/active"):
        if not active_monitors:
            await _send_bot_message(chat_id, "🔴 <b>No active monitors</b>")
        else:
            msg = "🔴 <b>Active Monitors:</b>\n\n"
            for addr, info in active_monitors.items():
                sym = info.get('symbol', '?')
                entry = info.get('entry_price', 0)
                snaps = info.get('snapshots', 0)
                msg += f"• <b>{sym}</b> | Entry: ${entry:.8f} | Snaps: {snaps}\n"
            await _send_bot_message(chat_id, msg)

    elif text.startswith("/help"):
        msg = (
            "🤖 <b>Meme Coin AI Agent Commands:</b>\n\n"
            "/status — Agent statistics & performance\n"
            "/tokens — Recent scanned tokens\n"
            "/active — Currently monitoring tokens\n"
            "/help — This message"
        )
        await _send_bot_message(chat_id, msg)

async def _send_bot_message(chat_id: int, text: str):
    import aiohttp
    url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    print(f"[Bot] Send failed {resp.status}: {err[:100]}")
    except Exception as e:
        print(f"[Bot] Send failed: {e}")

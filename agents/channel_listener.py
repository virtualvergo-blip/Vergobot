"""
agents/channel_listener.py
Listens to Telegram signal channels.
Classifies every message as SIGNAL_CALL / UPDATE / PROMO.
Only SIGNAL_CALL triggers monitoring. UPDATE enriches existing token records.
"""
import os
import asyncio
from datetime import datetime
from typing import Optional
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from utils.message_parser import (
    classify_message, MessageType,
    extract_signal_call, extract_update,
    ParsedSignalCall, ParsedUpdate,
)
from utils.data_fetcher import fetch_token_data, determine_chain
from database.db_manager import upsert_token, update_prediction_outcome
from agents.token_monitor import start_monitoring, active_monitors
from agents.notifier import (
    send_new_call_alert, send_update_alert, send_error_alert
)

API_ID         = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH       = os.getenv("TELEGRAM_API_HASH", "")
PHONE          = os.getenv("TELEGRAM_PHONE", "")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "")

SIGNAL_CHANNELS_RAW = os.getenv("SIGNAL_CHANNELS", "")
SIGNAL_CHANNELS     = [c.strip() for c in SIGNAL_CHANNELS_RAW.split(",") if c.strip()]

# Prevent duplicate processing within session
processed_calls: set = set()   # contract addresses already triggered
MAX_RECENT = 1000


async def create_client():
    if SESSION_STRING:
        return TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    return TelegramClient("memeagent_session", API_ID, API_HASH)


async def start_listener(client: TelegramClient):
    if not SIGNAL_CHANNELS:
        print("[Listener] ⚠ No SIGNAL_CHANNELS configured!")
        return

    print(f"[Listener] Watching {len(SIGNAL_CHANNELS)} channel(s):")
    for ch in SIGNAL_CHANNELS:
        print(f"  → {ch}")

    @client.on(events.NewMessage(chats=SIGNAL_CHANNELS))
    async def handler(event):
        try:
            text = event.message.message or ""
            if not text.strip():
                return

            chat     = await event.get_chat()
            ch_name  = getattr(chat, "username", None) or getattr(chat, "title", "unknown")
            src      = f"@{ch_name}"

            msg_type = classify_message(text)

            print(f"\n[Listener] [{msg_type.value}] from {src}: {text[:60].strip()}...")

            if msg_type == MessageType.SIGNAL_CALL:
                await _handle_signal_call(text, src)

            elif msg_type == MessageType.UPDATE:
                await _handle_update(text, src)

            elif msg_type == MessageType.PROMO:
                print(f"[Listener] 🔇 Promo/ad — ignored")

            else:
                print(f"[Listener] ❓ Unknown message type — ignored")

        except Exception as e:
            print(f"[Listener] Handler error: {e}")
            await send_error_alert(f"Listener error: {str(e)[:200]}")

    print("[Listener] ✅ Ready. Listening for calls...")


# ─────────────────────────────────────────────
# Handle SIGNAL_CALL
# ─────────────────────────────────────────────
async def _handle_signal_call(text: str, source: str):
    parsed = extract_signal_call(text)
    if not parsed:
        print(f"[Listener] ⚠ SIGNAL_CALL tapi contract address tidak ditemukan")
        return

    addr  = parsed.contract_address
    chain = determine_chain(addr)

    print(f"[Listener] 📡 New call: {parsed.token_symbol or '?'} "
          f"({addr[:8]}...) chain={chain}")

    # Skip if already processing this address
    if addr in processed_calls:
        print(f"[Listener] ↩ Already processing {addr[:8]}...")
        return

    processed_calls.add(addr)
    if len(processed_calls) > MAX_RECENT:
        # Trim oldest 100
        for old in list(processed_calls)[:100]:
            processed_calls.discard(old)

    # Fetch live data (GMGN → Helius → DexScreener)
    token_data = await fetch_token_data(addr, chain)
    if not token_data:
        print(f"[Listener] ✗ No price data found for {addr[:8]}")
        return

    # Enrich token_data with parsed call metadata
    token_data = _enrich_with_parsed(token_data, parsed)

    symbol = token_data.get("symbol") or parsed.token_symbol or "UNKNOWN"
    print(f"[Listener] ✓ {symbol} | "
          f"MC=${token_data.get('market_cap',0):,.0f} | "
          f"Age={parsed.age_minutes}m | "
          f"Holders={parsed.total_holders} | "
          f"Top10={parsed.top10_pct}% | "
          f"Sniper={parsed.sniper_count} | "
          f"DevSold={parsed.dev_sold} | "
          f"src={token_data.get('source','?')}")

    # Save to DB
    is_new = await upsert_token(
        contract_address=addr,
        symbol=symbol,
        name=token_data.get("name") or parsed.token_name,
        chain=chain,
        call_source=source,
        call_message=text[:500],
    )

    if is_new:
        # FIX: send_new_call_alert hanya menerima 4 argumen, parsed sudah di-merge ke token_data
        await send_new_call_alert(symbol, addr, token_data, source)
        await start_monitoring(addr, token_data)
    else:
        print(f"[Listener] {symbol} already in DB — skipping fresh monitor")


# ─────────────────────────────────────────────
# Handle UPDATE
# ─────────────────────────────────────────────
async def _handle_update(text: str, source: str):
    parsed = extract_update(text)

    mult    = parsed.multiplier
    sym     = parsed.token_symbol or parsed.token_name or "?"
    mins    = parsed.within_minutes
    mc_from = parsed.mc_from
    mc_to   = parsed.mc_to
    premium = parsed.premium_multiplier

    print(f"[Listener] 🔔 Update: {sym} | "
          f"{mult}x{'('+str(premium)+'x PREMIUM)' if premium else ''} | "
          f"MC {_fmt(mc_from)} → {_fmt(mc_to)} | "
          f"in {mins}m")

    # Forward update alert to user
    await send_update_alert(
        symbol=sym,
        multiplier=mult,
        premium_multiplier=premium,
        mc_from=mc_from,
        mc_to=mc_to,
        within_minutes=mins,
        source=source,
    )

    # If we have the contract address and it's being monitored,
    # record the actual multiplier for winrate tracking
    if parsed.contract_address and mult:
        addr = parsed.contract_address
        if addr in active_monitors:
            await update_prediction_outcome(addr, mult)
            print(f"[Listener] 📊 Winrate updated for {addr[:8]}: actual {mult}x")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _enrich_with_parsed(token_data: dict, parsed: ParsedSignalCall) -> dict:
    """
    Merge parsed call metadata into token_data dict.
    Parsed data from channel often more up-to-date for age/holders/dev status.
    """
    if parsed.token_name   and not token_data.get("name"):
        token_data["name"]   = parsed.token_name
    if parsed.token_symbol and not token_data.get("symbol"):
        token_data["symbol"] = parsed.token_symbol
    if parsed.total_holders:
        token_data["holder_count"]   = parsed.total_holders
    if parsed.top10_pct is not None:
        token_data["top_10_holder_rate"] = parsed.top10_pct
    if parsed.sniper_count is not None:
        token_data["sniper_count"]   = parsed.sniper_count
    if parsed.bundle_count is not None:
        token_data["bundle_count"]   = parsed.bundle_count
    if parsed.bundle_pct is not None:
        token_data["bundle_pct"]     = parsed.bundle_pct
    if parsed.dev_sold is not None:
        token_data["dev_sold"]       = parsed.dev_sold
    if parsed.dex_paid is not None:
        token_data["dex_paid"]       = parsed.dex_paid
    if parsed.age_minutes is not None:
        token_data["age_minutes"]    = parsed.age_minutes
    if parsed.gmgn_url:
        token_data["dex_url"]        = parsed.gmgn_url
    return token_data


def _fmt(val: Optional[float]) -> str:
    if val is None:
        return "?"
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val/1_000:.1f}K"
    return f"${val:.0f}"

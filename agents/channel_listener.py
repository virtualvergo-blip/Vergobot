"""
agents/channel_listener.py
FIXED: Better logging, correct handler flow, immediate AI analysis on call.
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
from utils.data_fetcher import fetch_token_data, determine_chain, fetch_full_analysis_bundle
from database.db_manager import upsert_token, update_prediction_outcome_by_address, save_prediction
from agents.token_monitor import start_monitoring, active_monitors
from agents.notifier import (
    send_new_call_alert, send_update_alert, send_error_alert, send_prediction_alert
)
from agents.ai_analyzer import analyze_token_pattern

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
PHONE = os.getenv("TELEGRAM_PHONE", "")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "")

SIGNAL_CHANNELS_RAW = os.getenv("SIGNAL_CHANNELS", "")
SIGNAL_CHANNELS = [c.strip() for c in SIGNAL_CHANNELS_RAW.split(",") if c.strip()]

processed_calls: set = set()
MAX_RECENT = 1000

async def create_client():
    if SESSION_STRING:
        return TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    return TelegramClient("memeagent_session", API_ID, API_HASH)

async def start_listener(client: TelegramClient):
    if not SIGNAL_CHANNELS:
        print("[Listener] No SIGNAL_CHANNELS configured!")
        return

    print("[Listener] Watching " + str(len(SIGNAL_CHANNELS)) + " channel(s):")
    for ch in SIGNAL_CHANNELS:
        print(" -> " + ch)

    # Resolve entities
    resolved = []
    for ch in SIGNAL_CHANNELS:
        try:
            entity = await client.get_entity(ch)
            resolved.append(entity)
            print("[Listener] Resolved: " + ch + " -> " + str(getattr(entity, 'title', ch)))
        except Exception as e:
            print("[Listener] Gagal resolve " + ch + ": " + str(e))

    if not resolved:
        print("[Listener] ⚠️ Tidak ada channel yang berhasil di-resolve.")
        print("[Listener] Pastikan bot sudah join channel dan session valid.")
        return

    print(f"[Listener] ✅ Resolved {len(resolved)}/{len(SIGNAL_CHANNELS)} channel(s)")

    @client.on(events.NewMessage(chats=resolved))
    async def handler(event):
        try:
            text = event.message.message or ""
            if not text.strip():
                return

            chat = await event.get_chat()
            ch_name = getattr(chat, "username", None) or getattr(chat, "title", "unknown")
            src = "@" + ch_name

            msg_type = classify_message(text)

            # LOG semua pesan untuk debugging
            print(f"\n[Listener] 📨 [{msg_type.value}] from {src}")
            print(f"[Listener] Content: {text[:120].replace(chr(10), ' | ')}...")

            if msg_type == MessageType.SIGNAL_CALL:
                print(f"[Listener] 🎯 SIGNAL_CALL detected! Processing...")
                await _handle_signal_call(text, src)
            elif msg_type == MessageType.UPDATE:
                print(f"[Listener] 📈 UPDATE detected! Logging outcome...")
                await _handle_update(text, src)
            elif msg_type == MessageType.PROMO:
                print("[Listener] 🚫 PROMO/ADS ignored")
            else:
                print("[Listener] ❓ Unknown message type ignored")
                # Debug: show why it wasn't classified
                if _has_contract_address(text):
                    print("[Listener]    (Has CA but not recognized as CALL — check parser)")

        except Exception as e:
            print("[Listener] Handler error: " + str(e))
            await send_error_alert("Listener error: " + str(e)[:200])

    print("[Listener] Ready. Listening for calls...")

async def _handle_signal_call(text: str, source: str):
    parsed = extract_signal_call(text)
    if not parsed:
        print("[Listener] SIGNAL_CALL tapi contract address tidak ditemukan")
        return

    addr = parsed.contract_address
    chain = determine_chain(addr)

    print(f"[Listener] 🆕 New call: {str(parsed.token_symbol or '?')} ({addr[:8]}...) chain={chain}")

    if addr in processed_calls:
        print("[Listener] Already processing " + addr[:8] + "...")
        return

    processed_calls.add(addr)
    if len(processed_calls) > MAX_RECENT:
        for old in list(processed_calls)[:100]:
            processed_calls.discard(old)

    token_data = await fetch_token_data(addr, chain)
    if not token_data:
        print("[Listener] No price data found for " + addr[:8])
        return

    token_data = _enrich_with_parsed(token_data, parsed)
    symbol = token_data.get("symbol") or parsed.token_symbol or "UNKNOWN"

    is_new = await upsert_token(
        contract_address=addr,
        symbol=symbol,
        name=token_data.get("name") or parsed.token_name,
        chain=chain,
        call_source=source,
        call_message=text[:500],
    )

    if is_new:
        # Send new call alert
        await send_new_call_alert(symbol, addr, token_data, source)

        # ── IMMEDIATE AI ANALYSIS ──
        # Analyze token immediately when call comes in, not just at end of session
        print(f"[Listener] 🤖 Running initial AI analysis for {symbol}...")
        try:
            bundle = await fetch_full_analysis_bundle(addr, chain)

            initial_prediction = await analyze_token_pattern(
                token_data=token_data,
                price_history=[],  # No history yet
                timeframe_stats={
                    "snapshots": 0,
                    "entry_price": token_data.get("price_usd", 0),
                    "first_price": token_data.get("price_usd", 0),
                    "current_price": token_data.get("price_usd", 0),
                },
                analysis_bundle=bundle,
            )

            if initial_prediction:
                print(f"[Listener] 🧠 AI Prediction: {initial_prediction.get('prediction_type')} "
                      f"| Confidence: {initial_prediction.get('confidence', 0):.2f}")

                # Save prediction
                pred_id = await save_prediction(
                    contract_address=addr,
                    prediction_type=initial_prediction.get("prediction_type", "UNKNOWN"),
                    predicted_multiplier=initial_prediction.get("predicted_multiplier", 1.0),
                    safe_tp_multiplier=initial_prediction.get("safe_tp_multiplier", 1.0),
                    confidence=initial_prediction.get("confidence", 0),
                    reasoning=initial_prediction.get("reasoning", ""),
                    ai_raw=initial_prediction.get("ai_raw_response", ""),
                )

                # Send prediction alert immediately
                await send_prediction_alert(
                    symbol=symbol,
                    contract_address=addr,
                    token_data=token_data,
                    prediction=initial_prediction,
                    timeframe_stats={"snapshots": 0, "max_gain_pct": 0},
                )
                print(f"[Listener] ✅ Initial prediction alert sent for {symbol}")
            else:
                print(f"[Listener] ⚠️ AI analysis returned None for {symbol}")

        except Exception as e:
            print(f"[Listener] ⚠️ Initial AI analysis failed: {e}")
            import traceback
            traceback.print_exc()

        # Start monitoring (continues in background)
        await start_monitoring(addr, token_data)
    else:
        print("[Listener] " + symbol + " already in DB - skipping")

async def _handle_update(text: str, source: str):
    parsed = extract_update(text)

    mult = parsed.multiplier
    sym = parsed.token_symbol or parsed.token_name or "?"
    mins = parsed.within_minutes
    mc_from = parsed.mc_from
    mc_to = parsed.mc_to
    premium = parsed.premium_multiplier

    print(f"[Listener] 📈 Update: {sym} | {mult}x | MC: {mc_from}→{mc_to} | {mins}m")

    await send_update_alert(
        symbol=sym,
        multiplier=mult,
        premium_multiplier=premium,
        mc_from=mc_from,
        mc_to=mc_to,
        within_minutes=mins,
        source=source,
    )

    if parsed.contract_address and mult:
        addr = parsed.contract_address
        # Update prediction outcome for learning
        await update_prediction_outcome_by_address(addr, mult)
        print("[Listener] Winrate updated for " + addr[:8] + ": actual " + str(mult) + "x")

def _enrich_with_parsed(token_data: dict, parsed: ParsedSignalCall) -> dict:
    if parsed.token_name and not token_data.get("name"):
        token_data["name"] = parsed.token_name
    if parsed.token_symbol and not token_data.get("symbol"):
        token_data["symbol"] = parsed.token_symbol
    if parsed.total_holders:
        token_data["holder_count"] = parsed.total_holders
    if parsed.top10_pct is not None:
        token_data["top_10_holder_rate"] = parsed.top10_pct
    if parsed.sniper_count is not None:
        token_data["sniper_count"] = parsed.sniper_count
    if parsed.bundle_count is not None:
        token_data["bundle_count"] = parsed.bundle_count
    if parsed.bundle_pct is not None:
        token_data["bundle_pct"] = parsed.bundle_pct
    if parsed.dev_sold is not None:
        token_data["dev_sold"] = parsed.dev_sold
    if parsed.dex_paid is not None:
        token_data["dex_paid"] = parsed.dex_paid
    if parsed.age_minutes is not None:
        token_data["age_minutes"] = parsed.age_minutes
    if parsed.gmgn_url:
        token_data["dex_url"] = parsed.gmgn_url
    return token_data

def _has_contract_address(text: str) -> bool:
    """Helper untuk debug."""
    import re
    SOL_ADDRESS_RE = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')
    EVM_ADDRESS_RE = re.compile(r'\b0x[a-fA-F0-9]{40}\b')
    if EVM_ADDRESS_RE.search(text):
        return True
    for match in SOL_ADDRESS_RE.finditer(text):
        addr = match.group()
        if len(addr) >= 32 and "http" not in addr:
            return True
    return False

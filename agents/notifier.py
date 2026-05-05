"""
agents/notifier.py
Sends Telegram notifications via Bot API.
Enhanced with GMGN security flags, candle data, and holder intel.
"""
import os
import html
import asyncio
import aiohttp
from typing import Dict, Any, Optional
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("YOUR_CHAT_ID", "")

EMOJI = {
    "PUMP":        "🚀",
    "DUMP":        "🩸",
    "RUG":         "💀",
    "CONSOLIDATE": "😴",
    "ACCUMULATE":  "🔄",
    "UNKNOWN":     "❓",
    "BUY_NOW":     "✅",
    "WAIT":        "⏳",
    "AVOID":       "🚫",
    "SELL":        "💰",
    "LOW":         "🟢",
    "MEDIUM":      "🟡",
    "HIGH":        "🔴",
    "EXTREME":     "☠️",
}


async def _send(text: str, parse_mode: str = "HTML"):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  CHAT_ID,
        "text":                     text,
        "parse_mode":               parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    print(f"[Notifier] Send failed {resp.status}: {err[:100]}")
    except Exception as e:
        print(f"[Notifier] Error: {e}")


# Public alias used by other modules
_send_message = _send


async def send_new_call_alert(symbol: str, contract_address: str,
                               token_data: dict, source_channel: str):
    chain    = token_data.get("chain", "?").upper()
    symbol = html.escape(str(symbol or "?"))
    price    = token_data.get("price_usd", 0)
    mcap     = token_data.get("market_cap", 0)
    liq      = token_data.get("liquidity_usd", 0)
    vol_5m   = token_data.get("volume_5m", 0)
    b_s      = token_data.get("buy_sell_ratio", 0)
    chg_5m   = token_data.get("price_change_5m", 0)
    chg_1h   = token_data.get("price_change_1h", 0)
    holders  = token_data.get("holder_count", "?")
    launchpad = token_data.get("launchpad", "?")
    dex_url  = token_data.get("dex_url", "")
    src      = token_data.get("source", "?")
    honeypot = "⚠️ YES" if token_data.get("is_honeypot") else "✅ No"
    renounced = "✅ Yes" if token_data.get("renounced") else "❌ No"
    top10pct = token_data.get("top_10_holder_rate")
    top10str = f"{top10pct:.1f}%" if top10pct else "?"

    addr_short = f"{contract_address[:6]}...{contract_address[-4:]}"

    text = (
        f"📡 <b>NEW CALL DETECTED</b>\n\n"
        f"🪙 <b>{symbol}</b> | {chain}\n"
        f"📌 <code>{addr_short}</code>\n"
        f"🏭 Launchpad: {launchpad}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Price:     <b>${price:.10f}</b>\n"
        f"💰 MCap:      <b>${mcap:,.0f}</b>\n"
        f"💧 Liquidity: <b>${liq:,.0f}</b>\n"
        f"📊 Vol 5m:    <b>${vol_5m:,.0f}</b>\n"
        f"⚖️  B/S Ratio: <b>{b_s:.2f}x</b>\n"
        f"📈 Chg 5m:    <b>{chg_5m:+.1f}%</b>\n"
        f"📈 Chg 1h:    <b>{chg_1h:+.1f}%</b>\n"
        f"👥 Holders:   <b>{holders}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡 Honeypot:  {honeypot}\n"
        f"🔓 Renounced: {renounced}\n"
        f"🐋 Top10 hold: {top10str}\n\n"
        f"📢 Source: {source_channel}\n"
        f"📡 Data: {src.upper()}\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC\n\n"
        f"<i>🔍 Agent monitoring all timeframes (GMGN candlestick)...</i>"
    )
    if dex_url:
        text += f"\n🔗 <a href='{dex_url}'>DexScreener Chart</a>"

    await _send(text)


async def send_prediction_alert(symbol: str, contract_address: str,
                                 token_data: dict, prediction: Dict[str, Any],
                                 timeframe_stats: Dict[str, Any]):
    symbol = html.escape(str(symbol or "?"))
    pred_type  = prediction.get("prediction_type", "UNKNOWN")
    confidence = prediction.get("confidence", 0)
    pred_x     = prediction.get("predicted_multiplier", 1.0)
    safe_tp_x  = prediction.get("safe_tp_multiplier", 1.0)
    peak_time  = prediction.get("peak_time_estimate_minutes", 30)
    sl_pct     = prediction.get("stop_loss_pct", -25)
    signals    = prediction.get("key_signals", [])
    reasoning  = prediction.get("reasoning", "")
    action     = prediction.get("action", "WAIT")
    risk       = prediction.get("risk_level", "HIGH")

    p_emo  = EMOJI.get(pred_type, "❓")
    a_emo  = EMOJI.get(action, "❓")
    r_emo  = EMOJI.get(risk, "🔴")

    price      = token_data.get("price_usd", 0)
    target_p   = price * pred_x
    safe_p     = price * safe_tp_x
    sl_p       = price * (1 + sl_pct / 100)

    max_gain   = timeframe_stats.get("max_gain_pct", 0)
    snaps      = timeframe_stats.get("snapshots", 0)

    # Confidence bar
    filled = int(confidence * 20)
    conf_bar = "█" * filled + "░" * (20 - filled)

    sigs_text  = "\n".join(f"  • {s}" for s in signals[:5])
    addr_short = f"{contract_address[:6]}...{contract_address[-4:]}"

    text = (
        f"{p_emo} <b>AI PREDICTION: {pred_type}</b>\n\n"
        f"🪙 <b>{symbol}</b> | <code>{addr_short}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Entry:    <b>${price:.10f}</b>\n"
        f"📈 Max gain: <b>+{max_gain:.1f}%</b> ({snaps} snapshots)\n\n"
        f"{a_emo} <b>ACTION: {action}</b>\n\n"
        f"🎯 Target:   <b>{pred_x:.1f}x</b> → <code>${target_p:.10f}</code>\n"
        f"✅ Safe TP:  <b>{safe_tp_x:.1f}x</b> → <code>${safe_p:.10f}</code>\n"
        f"🛑 Stop:     <b>{sl_pct}%</b> → <code>${sl_p:.10f}</code>\n"
        f"⏱ Peak est: ~<b>{peak_time} min</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 Confidence: {round(confidence*100)}%\n"
        f"[{conf_bar}]\n"
        f"{r_emo} Risk: <b>{risk}</b>\n\n"
        f"📊 <b>Signals:</b>\n{sigs_text}\n\n"
        f"💭 <i>{reasoning}</i>\n\n"
        f"⚠️ <i>Not financial advice. DYOR.</i>"
    )
    await _send(text)


async def send_update_alert(
    symbol: str,
    multiplier: Optional[float],
    premium_multiplier: Optional[float],
    mc_from: Optional[float],
    mc_to: Optional[float],
    within_minutes: Optional[int],
    source: str,
):
    """Send update notification when channel posts a price update on a called token."""
    from typing import Optional  # already imported but guard anyway

    mult_str = f"{multiplier:.1f}x" if multiplier else "?x"
    prem_str = f" ({premium_multiplier:.1f}x dari PREMIUM)" if premium_multiplier else ""

    def _fmt(v):
        if v is None: return "?"
        if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
        if v >= 1_000: return f"${v/1_000:.1f}K"
        return f"${v:.0f}"

    mc_str = f"{_fmt(mc_from)} → {_fmt(mc_to)}" if mc_from else "?"
    time_str = f"{within_minutes}m" if within_minutes else "?"

    # Emoji based on multiplier
    if multiplier and multiplier >= 10:
        emo = "🚀🚀🚀"
    elif multiplier and multiplier >= 5:
        emo = "🚀🚀"
    elif multiplier and multiplier >= 2:
        emo = "🚀"
    else:
        emo = "📈"

    text = (
        f"{emo} <b>UPDATE: {symbol}</b>\n\n"
        f"💹 Gain:    <b>{mult_str}{prem_str}</b>\n"
        f"💰 MC:      <b>{mc_str}</b>\n"
        f"⏱ Dalam:   <b>{time_str}</b>\n\n"
        f"📢 {source}"
    )
    await _send(text)


async def send_pattern_learned_alert(symbol: str, contract_address: str,
                                      pattern_type: str, stats: Dict):
    max_gain = stats.get("max_gain_pct", 0)
    symbol = html.escape(str(symbol or "?"))
    overall  = stats.get("overall_change_pct", 0)
    snaps    = stats.get("snapshots", 0)
    emoji    = "✅" if max_gain > 50 else ("⚠️" if max_gain > 20 else "❌")

    text = (
        f"{emoji} <b>PATTERN LEARNED</b>\n\n"
        f"🪙 <b>{symbol}</b>\n"
        f"📐 Pattern:  <b>{pattern_type}</b>\n"
        f"📈 Max Gain: <b>+{max_gain:.1f}%</b>\n"
        f"📉 Net:      <b>{overall:+.1f}%</b>\n"
        f"📸 Snaps:    {snaps}\n\n"
        f"<i>✅ Saved to database. Agent learning...</i>"
    )
    await _send(text)


async def send_status_message(stats: Dict[str, Any], active_count: int):
    total_tokens = stats.get("total_tokens", 0)
    winrate      = stats.get("winrate_pct", 0)
    total_preds  = stats.get("total_predictions", 0)
    correct      = stats.get("correct_predictions", 0)
    avg_conf     = stats.get("avg_confidence", 0)
    outcomes     = stats.get("pattern_outcomes", {})

    filled   = int(winrate / 5)
    bar      = "█" * filled + "░" * (20 - filled)
    out_text = "\n".join(f"  • {k}: {v}" for k, v in outcomes.items()) if outcomes else "  No data yet"

    text = (
        f"📊 <b>MEME AGENT STATUS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🗄 <b>Database:</b>\n"
        f"  • Tokens scanned: <b>{total_tokens}</b>\n"
        f"  • Patterns: <b>{sum(outcomes.values()) if outcomes else 0}</b>\n\n"
        f"🎯 <b>Performance:</b>\n"
        f"  • Winrate: <b>{winrate}%</b>\n"
        f"  [{bar}]\n"
        f"  • Predictions: {total_preds} total | {correct} correct\n"
        f"  • Avg confidence: <b>{avg_conf}%</b>\n\n"
        f"📐 <b>Pattern Breakdown:</b>\n{out_text}\n\n"
        f"🔴 <b>Active monitors:</b> {active_count}\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )
    await _send(text)


async def send_startup_message(channels: list):
    text = (
        f"🤖 <b>MEME AGENT ONLINE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ All systems active\n"
        f"📡 Monitoring {len(channels)} channel(s):\n"
        + "\n".join(f"  • {c}" for c in channels) +
        f"\n\n"
        f"🧠 AI:    Groq Llama 3.3 70B\n"
        f"📊 Data:  GMGN (candles + security)\n"
        f"⛓  RPC:   Helius (on-chain)\n"
        f"📉 FB:    DexScreener\n"
        f"💾 DB:    SQLite local\n\n"
        f"/status  /tokens  /active  /help\n\n"
        f"<i>Listening for calls...</i>"
    )
    await _send(text)


async def send_error_alert(error_msg: str):
    text = (
        f"⚠️ <b>AGENT ERROR</b>\n\n"
        f"<code>{error_msg[:300]}</code>\n\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
    )
    await _send(text)

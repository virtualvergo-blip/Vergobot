"""
agents/token_monitor.py

Monitor token selama MONITOR_DURATION menit (default 60).
FIXED: 
- Properly calls update_prediction_outcome with prediction_id
- Continues monitoring after initial AI analysis
- Better error handling
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Dict

from utils.data_fetcher import fetch_price_only
from database.db_manager import (
    save_price_snapshot, get_price_history,
    save_pattern, save_prediction, update_prediction_outcome,
    update_stat,
)
from agents.ai_analyzer import (
    analyze_token_pattern, classify_pattern_type, calculate_timeframe_stats,
)
from agents.notifier import send_prediction_alert, send_pattern_learned_alert

MONITOR_DURATION = int(os.getenv("MONITOR_DURATION_MINUTES", 60))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 60))
WIN_MULTIPLIER = float(os.getenv("WIN_MULTIPLIER", 1.5))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", 0.60))

active_monitors: Dict[str, dict] = {}
monitoring_tasks: Dict[str, asyncio.Task] = {}

async def start_monitoring(contract_address: str, token_info: dict):
    if contract_address in monitoring_tasks:
        print(f"[Monitor] {contract_address[:8]}... already being monitored")
        return
    task = asyncio.create_task(_monitor_loop(contract_address, token_info))
    monitoring_tasks[contract_address] = task
    await update_stat("active_monitors", str(len(monitoring_tasks)))

async def _monitor_loop(contract_address: str, initial_info: dict):
    symbol = initial_info.get("symbol", contract_address[:8])
    chain = initial_info.get("chain", "sol")
    start_time = datetime.now(timezone.utc)
    end_time = start_time + timedelta(minutes=MONITOR_DURATION)
    entry_price = float(initial_info.get("price_usd", 0.0))

    active_monitors[contract_address] = {
        "start_time": start_time,
        "symbol": symbol,
        "entry_price": entry_price,
        "snapshots": 0,
    }
    print(f"[Monitor] ▶ {symbol} | entry=${entry_price:.8f} | monitoring for {MONITOR_DURATION}m | end {end_time.strftime('%H:%M')} UTC")

    try:
        # ── Poll loop: setiap POLL_INTERVAL detik ──
        while datetime.now(timezone.utc) < end_time:
            data = await fetch_price_only(contract_address, chain)
            if not data:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            price = float(data.get("price_usd", 0.0))

            await save_price_snapshot(
                contract_address=contract_address,
                price_usd=price,
                market_cap=data.get("market_cap", 0),
                volume_24h=data.get("volume_24h", 0),
                price_change_pct=data.get("price_change_5m", 0),
                liquidity=data.get("liquidity_usd", 0),
                buys=data.get("buys_5m", 0),
                sells=data.get("sells_5m", 0),
                timeframe="1m",
            )
            active_monitors[contract_address]["snapshots"] += 1

            if entry_price == 0.0 and price > 0:
                entry_price = price
                active_monitors[contract_address]["entry_price"] = entry_price

            # Log progress every 10 snapshots
            snaps = active_monitors[contract_address]["snapshots"]
            if snaps % 10 == 0:
                current_gain = ((price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                print(f"[Monitor] {symbol} | snap #{snaps} | price=${price:.8f} | gain={current_gain:+.1f}%")

            await asyncio.sleep(POLL_INTERVAL)

        # ── Akhir session ──
        print(f"[Monitor] ⏹ {symbol} session ended. Analyzing pattern...")

        final_history = await get_price_history(contract_address, limit=500)
        if not final_history:
            print(f"[Monitor] ⚠️ No price history for {symbol}")
            return

        stats = calculate_timeframe_stats(final_history)
        pattern = await classify_pattern_type(final_history)
        prices = [p["price_usd"] for p in final_history if p.get("price_usd", 0) > 0]

        if not prices:
            print(f"[Monitor] ⚠️ No valid prices for {symbol}")
            return

        final_price = prices[-1]
        peak_price = max(prices)
        max_gain = stats.get("max_gain_pct", 0)
        final_mult = (final_price / entry_price) if entry_price > 0 and final_price > 0 else 1.0
        rug_detected = (
            stats.get("max_drawdown_pct", 0) > 80 or
            (max_gain > 100 and stats.get("overall_change_pct", 0) < -50)
        )
        outcome = (
            "WIN" if final_mult >= WIN_MULTIPLIER else
            "DUMP" if final_mult < 0.7 else
            "NEUTRAL"
        )
        peak_idx = prices.index(peak_price) if peak_price in prices else 0
        time_to_peak = (peak_idx * POLL_INTERVAL) // 60

        await save_pattern(
            contract_address=contract_address,
            pattern_type=pattern,
            pattern_data=stats,
            timeframe=f"{MONITOR_DURATION}m",
            max_gain_pct=max_gain,
            max_dump_pct=abs(stats.get("max_drawdown_pct", 0)),
            time_to_peak_minutes=time_to_peak,
            rug_detected=rug_detected,
            outcome=outcome,
        )
        print(f"[Monitor] ✅ Pattern saved: {symbol} | {pattern} | gain={max_gain:.1f}% | {final_mult:.2f}x | {outcome}")

        # ── AI analysis at end of session (for pattern learning) ──
        # Note: Initial AI analysis already done in channel_listener when call first arrived
        # This is the follow-up analysis with full price history
        final_data = {
            "price_usd": final_price, 
            "market_cap": data.get("market_cap", 0) if 'data' in dir() else 0
        }

        end_prediction = await analyze_token_pattern(
            token_data=final_data,
            price_history=final_history,
            timeframe_stats=stats,
            analysis_bundle=None,
        )

        if end_prediction and end_prediction.get("confidence", 0) >= MIN_CONFIDENCE:
            pred_id = await save_prediction(
                contract_address=contract_address,
                prediction_type=end_prediction.get("prediction_type", "UNKNOWN"),
                predicted_multiplier=end_prediction.get("predicted_multiplier", 1.0),
                safe_tp_multiplier=end_prediction.get("safe_tp_multiplier", 1.0),
                confidence=end_prediction.get("confidence", 0),
                reasoning=end_prediction.get("reasoning", ""),
                ai_raw=end_prediction.get("ai_raw_response", ""),
            )

            if pred_id:
                # FIXED: Use prediction_id, not contract_address
                await update_prediction_outcome(pred_id, final_mult)
                print(f"[Monitor] ✅ End-session prediction saved and resolved for {symbol}")

            await send_prediction_alert(
                symbol=symbol,
                contract_address=contract_address,
                token_data=final_data,
                prediction=end_prediction,
                timeframe_stats=stats,
            )

        await send_pattern_learned_alert(symbol, contract_address, pattern, stats)
        print(f"[Monitor] 📚 Pattern learned alert sent for {symbol}")

    except asyncio.CancelledError:
        print(f"[Monitor] {symbol} cancelled")
    except Exception as e:
        print(f"[Monitor] ERROR {symbol}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        active_monitors.pop(contract_address, None)
        monitoring_tasks.pop(contract_address, None)
        await update_stat("active_monitors", str(len(monitoring_tasks)))
        print(f"[Monitor] 🧹 Cleaned up {symbol}")

def get_active_count() -> int:
    return len(monitoring_tasks)

async def stop_all():
    for task in list(monitoring_tasks.values()):
        task.cancel()
    monitoring_tasks.clear()
    active_monitors.clear()

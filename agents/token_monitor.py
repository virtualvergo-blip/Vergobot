"""
agents/token_monitor.py
Monitors token price at multiple timeframes.
Primary: GMGN candlestick + Helius on-chain. Fallback: DexScreener.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Dict

from utils.data_fetcher import (
    fetch_token_data,
    fetch_full_analysis_bundle,
)
from database.db_manager import (
    save_price_snapshot, get_price_history,
    save_pattern, save_prediction, update_stat,
)
from agents.ai_analyzer import (
    analyze_token_pattern, classify_pattern_type, calculate_timeframe_stats,
)
from agents.notifier import send_prediction_alert, send_pattern_learned_alert

MONITOR_DURATION = int(os.getenv("MONITOR_DURATION_MINUTES", 60))
MIN_CONFIDENCE   = float(os.getenv("MIN_CONFIDENCE", 0.65))

active_monitors:  Dict[str, dict] = {}
monitoring_tasks: Dict[str, asyncio.Task] = {}


async def start_monitoring(contract_address: str, token_info: dict):
    if contract_address in monitoring_tasks:
        return
    task = asyncio.create_task(_monitor_loop(contract_address, token_info))
    monitoring_tasks[contract_address] = task
    await update_stat("active_monitors", str(len(monitoring_tasks)))


async def _monitor_loop(contract_address: str, initial_token_info: dict):
    symbol     = initial_token_info.get("symbol", contract_address[:8])
    chain      = initial_token_info.get("chain", "sol")
    start_time = datetime.now(timezone.utc)
    end_time   = start_time + timedelta(minutes=MONITOR_DURATION)

    active_monitors[contract_address] = {
        "start_time":    start_time,
        "symbol":        symbol,
        "initial_price": initial_token_info.get("price_usd", 0),
        "snapshots":     0,
    }
    print(f"[Monitor] ▶ {symbol} until {end_time.strftime('%H:%M:%S')} UTC")

    last_15s = last_30s = last_1m = last_5m = last_10m = datetime.now(timezone.utc)
    last_analysis     = datetime.now(timezone.utc)
    last_bundle_fetch = datetime.now(timezone.utc)

    initial_snapshot = None
    prediction_sent  = False
    cached_bundle    = None

    try:
        # Fast first bundle (includes candles, security, holders)
        cached_bundle = await fetch_full_analysis_bundle(contract_address, chain)

        while datetime.now(timezone.utc) < end_time:
            now = datetime.now(timezone.utc)

            data = await fetch_token_data(contract_address, chain)
            if not data:
                await asyncio.sleep(15)
                continue

            # Determine timeframe label
            timeframe = "5s"
            if (now - last_15s).total_seconds() >= 15:  timeframe = "15s"; last_15s = now
            if (now - last_30s).total_seconds() >= 30:  timeframe = "30s"; last_30s = now
            if (now - last_1m).total_seconds()  >= 60:  timeframe = "1m";  last_1m  = now
            if (now - last_5m).total_seconds()  >= 300: timeframe = "5m";  last_5m  = now
            if (now - last_10m).total_seconds() >= 600: timeframe = "10m"; last_10m = now

            await save_price_snapshot(
                contract_address=contract_address,
                price_usd=data.get("price_usd", 0),
                market_cap=data.get("market_cap", 0),
                volume_24h=data.get("volume_24h", 0),
                price_change_pct=data.get("price_change_5m", 0),
                liquidity=data.get("liquidity_usd", 0),
                buys=data.get("buys_5m", 0),
                sells=data.get("sells_5m", 0),
                timeframe=timeframe,
            )

            if initial_snapshot is None:
                initial_snapshot = data.copy()
            active_monitors[contract_address]["snapshots"] += 1

            # Refresh GMGN bundle every 5 min
            if (now - last_bundle_fetch).total_seconds() >= 300:
                fresh = await fetch_full_analysis_bundle(contract_address, chain)
                if fresh:
                    cached_bundle = fresh
                last_bundle_fetch = now

            # AI analysis: first at 30s, then every 90s
            elapsed = (now - start_time).total_seconds()
            since_analysis = (now - last_analysis).total_seconds()
            should_analyze = (
                (not prediction_sent and elapsed >= 30) or
                (prediction_sent and since_analysis >= 90)
            )

            if should_analyze:
                last_analysis   = now
                price_history   = await get_price_history(contract_address, limit=120)
                timeframe_stats = calculate_timeframe_stats(price_history)

                print(f"[Monitor] 🧠 Analyzing {symbol} "
                      f"({len(price_history)} snaps | bundle={'✓' if cached_bundle else '✗'})...")

                prediction = await analyze_token_pattern(
                    token_data=data,
                    price_history=price_history,
                    timeframe_stats=timeframe_stats,
                    analysis_bundle=cached_bundle,
                )

                if prediction and prediction.get("confidence", 0) >= MIN_CONFIDENCE:
                    await save_prediction(
                        contract_address=contract_address,
                        prediction_type=prediction.get("prediction_type", "UNKNOWN"),
                        predicted_multiplier=prediction.get("predicted_multiplier", 1.0),
                        safe_tp_multiplier=prediction.get("safe_tp_multiplier", 1.0),
                        confidence=prediction.get("confidence", 0),
                        reasoning=prediction.get("reasoning", ""),
                        ai_raw=prediction.get("ai_raw_response", ""),
                    )
                    if not prediction_sent or prediction.get("prediction_type") in ("RUG", "DUMP"):
                        await send_prediction_alert(
                            symbol=symbol,
                            contract_address=contract_address,
                            token_data=data,
                            prediction=prediction,
                            timeframe_stats=timeframe_stats,
                        )
                        prediction_sent = True

            await asyncio.sleep(15)  # 15s — cukup untuk catch pump cepat, tidak kena rate limit GMGN

        # End of session — save pattern
        final_history = await get_price_history(contract_address, limit=1000)
        if final_history and initial_snapshot:
            pattern_type  = await classify_pattern_type(final_history)
            stats         = calculate_timeframe_stats(final_history)
            init_price    = initial_snapshot.get("price_usd", 0)
            max_gain_pct  = stats.get("max_gain_pct", 0)
            prices        = [p["price_usd"] for p in final_history if p.get("price_usd")]
            max_idx       = prices.index(max(prices)) if prices else 0
            time_to_peak  = (max_idx * 5) // 60
            last_price    = prices[-1] if prices else 0
            peak_price    = init_price * (1 + max_gain_pct / 100)
            dump_pct      = (last_price - peak_price) / peak_price * 100 if peak_price > 0 else 0
            rug_detected  = (
                stats.get("max_drawdown_pct", 0) > 80 or
                (max_gain_pct > 100 and stats.get("overall_change_pct", 0) < -50)
            )
            outcome = (
                "WIN"  if max_gain_pct > 50 else
                "DUMP" if stats.get("overall_change_pct", 0) < -30 else
                "NEUTRAL"
            )
            await save_pattern(
                contract_address=contract_address, pattern_type=pattern_type,
                pattern_data=stats, timeframe="session", max_gain_pct=max_gain_pct,
                max_dump_pct=abs(dump_pct), time_to_peak_minutes=time_to_peak,
                rug_detected=rug_detected, outcome=outcome,
            )
            await send_pattern_learned_alert(symbol, contract_address, pattern_type, stats)
            print(f"[Monitor] ✅ Pattern saved → {symbol}: {pattern_type} | gain={max_gain_pct:.1f}%")

    except asyncio.CancelledError:
        print(f"[Monitor] {symbol} cancelled")
    except Exception as e:
        print(f"[Monitor] ERROR {symbol}: {e}")
        import traceback; traceback.print_exc()
    finally:
        active_monitors.pop(contract_address, None)
        monitoring_tasks.pop(contract_address, None)
        await update_stat("active_monitors", str(len(monitoring_tasks)))


def get_active_count() -> int:
    return len(monitoring_tasks)


async def stop_all():
    for task in monitoring_tasks.values():
        task.cancel()
    monitoring_tasks.clear()
    active_monitors.clear()

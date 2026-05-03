"""
agents/ai_analyzer.py
Uses Groq (Llama 3.3 70B - free) to analyze meme coin patterns.
Now powered by GMGN candlestick data + Helius on-chain enrichment.
"""
import os
import json
from groq import AsyncGroq
from typing import Dict, Any, List, Optional
from database.db_manager import get_historical_patterns

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = "llama-3.3-70b-versatile"


async def analyze_token_pattern(
    token_data:      Dict[str, Any],
    price_history:   List[Dict],
    timeframe_stats: Dict[str, Any],
    analysis_bundle: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    Send token data to Groq for pattern analysis.
    analysis_bundle = full GMGN fetch (candles, security, holders, traders).
    Falls back gracefully to snapshot-only if bundle not available.
    """
    historical = await get_historical_patterns(limit=25)

    candle_summary = {}
    security_flags = {}
    holder_info    = {}

    if analysis_bundle:
        # ── Candle features per resolution
        cf = analysis_bundle.get("candle_features", {})
        for res, feat in cf.items():
            if feat and not feat.get("insufficient_data"):
                candle_summary[res] = feat

        # ── Security / rug risk
        sec = analysis_bundle.get("security") or {}
        security_flags = {
            "is_honeypot":           sec.get("is_honeypot", False),
            "renounced":             sec.get("renounced", False),
            "freeze_authority":      sec.get("freeze_authority"),
            "mint_authority":        sec.get("mint_authority"),
            "top10_holder_pct":      sec.get("top_10_holder_rate"),
            "rug_ratio":             sec.get("rug_ratio"),
            "bundled_supply":        sec.get("bundled_supply"),
            "top5_concentration_pct": analysis_bundle.get("top5_concentration_pct"),
        }

        # ── Holder / trader intel
        holders = analysis_bundle.get("holders") or []
        traders = analysis_bundle.get("traders") or []
        if traders:
            holder_info = {
                "holder_count":  token_data.get("holder_count"),
                "smart_traders": sum(1 for t in traders if t.get("is_smart_degen")),
                "kol_count":     sum(1 for t in traders if t.get("is_kol")),
                "insider_count": sum(1 for t in traders if t.get("is_insider")),
                "sniper_count":  sum(1 for t in traders if t.get("is_sniper")),
                "bluechip_pct":  next(
                    (t.get("bluechip_owner_percentage") for t in traders if t.get("bluechip_owner_percentage")),
                    None
                ),
            }

    # ── Compact snapshot history
    snap_summary = [
        {
            "t":   s["snapshot_at"][-8:],
            "p":   round(s["price_usd"] or 0, 10),
            "chg": round(s["price_change_pct"] or 0, 2),
            "b":   s["buys"]  or 0,
            "s":   s["sells"] or 0,
        }
        for s in price_history[-30:]
    ]

    # ── Historical few-shot examples
    hist_examples = [
        {
            "symbol":        p.get("symbol", "?"),
            "pattern":       p.get("pattern_type"),
            "max_gain_pct":  p.get("max_gain_pct"),
            "peak_minutes":  p.get("time_to_peak_minutes"),
            "rug":           bool(p.get("rug_detected")),
            "outcome":       p.get("outcome"),
        }
        for p in historical[:15]
    ]

    system_prompt = """You are an elite meme coin pattern recognition AI specialising in pump & dump dynamics, rug pulls, and momentum trading on Solana, BSC, and Base.

You receive multi-resolution OHLCV candlestick features (1m, 5m, 15m, 1h), on-chain security data from GMGN and Helius, holder/trader intel, and historical patterns the agent has learned.

PATTERN RULES:
- PUMP: vol_surge_ratio>3, bullish_candles>=4/5, buy_sell_ratio>2.5, price_change_pct>15%, low wick ratio
- DUMP: price_change_pct<-15%, bearish dominance, high upper wick ratio, vol spike then collapse
- RUG: price_change_pct<-50%, top5_concentration>60%, freeze_authority set, liquidity dropping
- ACCUMULATE: flat price, volume slowly building, smart/KOL traders buying, low sell pressure
- CONSOLIDATE: low vol, sideways, no clear direction

RISK ESCALATION:
- EXTREME: honeypot=true OR top5_concentration>70% OR sniper_count>5 OR freeze_authority set
- HIGH: top5>40% OR insider_count>3 OR renounced=false OR rug_ratio>0.5
- MEDIUM: top5 20-40% OR mixed signals
- LOW: renounced + locked liq + organic volume + smart traders buying

predicted_multiplier = expected peak from CURRENT price (e.g. 3.0 = 3x)
safe_tp_multiplier   = conservative exit (e.g. 2.0 = 2x, take profit here for safety)

RESPOND ONLY with valid JSON — no markdown, no extra text:
{
  "prediction_type": "PUMP|DUMP|RUG|CONSOLIDATE|ACCUMULATE",
  "confidence": 0.0-1.0,
  "predicted_multiplier": 1.0-20.0,
  "safe_tp_multiplier": 1.0-10.0,
  "peak_time_estimate_minutes": integer,
  "stop_loss_pct": -5 to -80,
  "key_signals": ["signal1", "signal2", "signal3", "signal4"],
  "risk_level": "LOW|MEDIUM|HIGH|EXTREME",
  "reasoning": "2 sentences max",
  "action": "BUY_NOW|WAIT|AVOID|SELL"
}"""

    user_prompt = f"""=== TOKEN ===
Symbol:    {token_data.get('symbol','?')} | {token_data.get('name','?')}
Chain:     {token_data.get('chain','?')}
Data src:  {token_data.get('source','?')}
Price:     ${token_data.get('price_usd',0):.10f}
MCap:      ${token_data.get('market_cap',0):,.0f}
FDV:       ${token_data.get('fdv',0):,.0f}
Liquidity: ${token_data.get('liquidity_usd',0):,.0f}
Vol 5m:    ${token_data.get('volume_5m',0):,.0f}
B/S ratio: {token_data.get('buy_sell_ratio',1):.2f}x
Chg 5m:    {token_data.get('price_change_5m',0):.1f}%
Chg 1h:    {token_data.get('price_change_1h',0):.1f}%
Launchpad: {token_data.get('launchpad','unknown')}

=== GMGN CANDLESTICK FEATURES ===
{json.dumps(candle_summary, indent=2) if candle_summary else "Not available (DexScreener fallback mode)"}

=== SECURITY / RUG RISK (GMGN + Helius) ===
{json.dumps(security_flags, indent=2) if security_flags else "Not available"}

=== HOLDER / TRADER INTEL ===
{json.dumps(holder_info, indent=2) if holder_info else "Not available"}

=== OUR SNAPSHOT HISTORY (last 30 polls) ===
{json.dumps(snap_summary, indent=1)}

=== CURRENT SESSION STATS ===
{json.dumps(timeframe_stats, indent=2)}

=== HISTORICAL LEARNED PATTERNS (few-shot) ===
{json.dumps(hist_examples, indent=1)}

Return JSON prediction only."""

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.25,
            max_tokens=700,
        )

        raw = response.choices[0].message.content.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        result = json.loads(raw)
        result["ai_raw_response"] = raw
        return result

    except json.JSONDecodeError as e:
        print(f"[AI] JSON parse error: {e}")
        return _fallback_prediction()
    except Exception as e:
        print(f"[AI] Groq error: {e}")
        return None


def _fallback_prediction() -> Dict:
    return {
        "prediction_type":            "UNKNOWN",
        "confidence":                 0.1,
        "predicted_multiplier":       1.0,
        "safe_tp_multiplier":         1.0,
        "peak_time_estimate_minutes": 30,
        "stop_loss_pct":              -25,
        "key_signals":                ["analysis_failed"],
        "risk_level":                 "HIGH",
        "reasoning":                  "AI analysis failed — parse error.",
        "action":                     "AVOID",
        "ai_raw_response":            "",
    }


async def classify_pattern_type(price_history: List[Dict]) -> str:
    if len(price_history) < 3:
        return "INSUFFICIENT_DATA"
    prices = [p["price_usd"] for p in price_history if p.get("price_usd")]
    if not prices:
        return "NO_PRICE"
    first = prices[0]
    peak  = max(prices)
    last  = prices[-1]
    if first == 0:
        return "ZERO_PRICE"
    gain          = (peak - first) / first * 100
    drop_from_peak = (peak - last)  / peak  * 100 if peak > 0 else 0
    if gain > 300 and drop_from_peak > 80:
        return "RUG_PULL"
    if gain > 200 and drop_from_peak > 60:
        return "PUMP_AND_DUMP"
    if gain > 100 and drop_from_peak < 25:
        return "SUSTAINED_PUMP"
    if gain > 50:
        return "MODERATE_PUMP"
    if last < first * 0.5:
        return "RUG_PULL"
    if last < first * 0.8:
        return "SLOW_DUMP"
    if abs(last - first) / first < 0.1:
        return "CONSOLIDATION"
    return "VOLATILE"


def calculate_timeframe_stats(price_history: List[Dict]) -> Dict[str, Any]:
    if not price_history:
        return {}
    prices  = [p["price_usd"]  for p in price_history if p.get("price_usd")]
    volumes = [p["volume_24h"] for p in price_history if p.get("volume_24h")]
    buys    = [p["buys"]       for p in price_history if p.get("buys")]
    sells   = [p["sells"]      for p in price_history if p.get("sells")]
    if not prices:
        return {}
    first = prices[0]
    mx    = max(prices)
    last  = prices[-1]
    stats: Dict[str, Any] = {
        "snapshots":          len(prices),
        "first_price":        first,
        "current_price":      last,
        "max_price":          mx,
        "min_price":          min(prices),
        "overall_change_pct": round((last - first) / first * 100, 2) if first else 0,
        "max_gain_pct":       round((mx - first)   / first * 100, 2) if first else 0,
        "max_drawdown_pct":   round((mx - min(prices)) / mx * 100, 2) if mx else 0,
        "avg_volume":         round(sum(volumes) / len(volumes)) if volumes else 0,
        "total_buys":         sum(buys)  if buys  else 0,
        "total_sells":        sum(sells) if sells else 0,
        "buy_sell_ratio":     round(sum(buys) / sum(sells), 2) if buys and sells and sum(sells) > 0 else 0,
    }
    if len(prices) >= 10:
        early  = sum(prices[:5]) / 5
        recent = sum(prices[-5:]) / 5
        stats["velocity_pct"] = round((recent - early) / early * 100, 2) if early else 0
    return stats

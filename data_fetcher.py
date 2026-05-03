"""
utils/data_fetcher.py

Multi-source data fetcher with priority:
  1. GMGN CLI (gmgn-cli via npm) — token info, kline, security, pool, holders, traders
     BUKAN REST API biasa — gunakan subprocess gmgn-cli dengan GMGN_API_KEY di env.
     Install: npm install -g gmgn-cli
  2. Helius RPC (on-chain token supply, holder count, real txn history) — Solana native
  3. DexScreener (fallback, price + liquidity)

gmgn-cli commands:
  gmgn-cli token info       --chain sol --address <addr> --raw
  gmgn-cli token security   --chain sol --address <addr> --raw
  gmgn-cli token pool       --chain sol --address <addr> --raw
  gmgn-cli token holders    --chain sol --address <addr> --raw
  gmgn-cli token traders    --chain sol --address <addr> --raw
  gmgn-cli market kline     --chain sol --address <addr> --resolution 1m --from <ts> --to <ts> --raw
  gmgn-cli market trending  --chain sol --interval 1h --limit 50 --raw
"""

import os
import re
import sys
import time
import json
import shutil
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
GMGN_API_KEY   = os.getenv("GMGN_API_KEY", "")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")

HELIUS_RPC       = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
DEXSCREENER_BASE = "https://api.dexscreener.com"

_SESSION: Optional[aiohttp.ClientSession] = None


async def _get_session() -> aiohttp.ClientSession:
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        _SESSION = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
    return _SESSION


# ─────────────────────────────────────────────
# GMGN CLI — subprocess helper
# GMGN bukan REST API biasa, gunakan gmgn-cli via npm
# ─────────────────────────────────────────────
async def _run_gmgn_cli(*args) -> Optional[Any]:
    """
    Run gmgn-cli command and return parsed JSON output.
    GMGN_API_KEY harus di-set di environment.
    Selalu append --raw agar output adalah JSON murni.
    """
    if not GMGN_API_KEY:
        return None

    env = os.environ.copy()
    env["GMGN_API_KEY"] = GMGN_API_KEY

    # Windows: npm install -g membuat wrapper .cmd, bukan binary langsung.
    # shutil.which() mencari gmgn-cli.cmd (Windows) atau gmgn-cli (Linux/Mac).
    cli_name = "gmgn-cli.cmd" if sys.platform == "win32" else "gmgn-cli"
    cli_path = shutil.which(cli_name) or shutil.which("gmgn-cli")

    if not cli_path:
        print("[gmgn-cli] NOT FOUND — pastikan sudah install: npm install -g gmgn-cli")
        return None

    cmd = [cli_path] + list(args) + ["--raw"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)

        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace")[:300]
            print(f"[gmgn-cli] returncode={proc.returncode} cmd={' '.join(cmd)}\n  stderr: {err_msg}")
            return None

        raw = stdout.decode(errors="replace").strip()
        if not raw:
            print(f"[gmgn-cli] Empty output for cmd: {' '.join(cmd)}")
            return None

        return json.loads(raw)

    except asyncio.TimeoutError:
        print(f"[gmgn-cli] Timeout (20s) cmd={' '.join(cmd)}")
        return None
    except json.JSONDecodeError as e:
        print(f"[gmgn-cli] JSON parse error: {e} — output: {stdout.decode(errors='replace')[:200]}")
        return None
    except Exception as e:
        print(f"[gmgn-cli] Error: {e}")
        return None


# ─────────────────────────────────────────────
# GMGN: Token Info (via gmgn-cli subprocess)
# ─────────────────────────────────────────────
async def gmgn_token_info(contract_address: str, chain: str = "sol") -> Optional[Dict]:
    """Fetch comprehensive token info via gmgn-cli."""
    data = await _run_gmgn_cli("token", "info", "--chain", chain, "--address", contract_address)
    if not data:
        return None
    return data.get("data") or data


# ─────────────────────────────────────────────
# GMGN: Candlestick (K-line) (via gmgn-cli subprocess)
# ─────────────────────────────────────────────
async def gmgn_kline(
    contract_address: str,
    chain: str = "sol",
    resolution: str = "1m",
    from_ts: Optional[int] = None,
    to_ts:   Optional[int] = None,
    limit:   int = 200
) -> Optional[List[Dict]]:
    """
    Fetch OHLCV candlestick data via gmgn-cli.
    resolution: 1m | 5m | 15m | 1h | 4h | 1d
    gmgn-cli market kline tidak punya --limit, gunakan --from / --to.
    """
    now     = int(time.time())
    to_ts   = to_ts   or now
    from_ts = from_ts or (now - limit * _res_seconds(resolution))

    args = [
        "market", "kline",
        "--chain",      chain,
        "--address",    contract_address,
        "--resolution", resolution,
        "--from",       str(from_ts),
        "--to",         str(to_ts),
    ]
    data = await _run_gmgn_cli(*args)
    if not data:
        return None

    raw = data.get("data") or data
    # Normalize: some responses wrap in {"list": [...]}
    candles = raw.get("list") if isinstance(raw, dict) else raw
    if not candles:
        return None
    return [_normalize_candle(c) for c in candles]


def _res_seconds(res: str) -> int:
    mapping = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    return mapping.get(res, 60)


def _normalize_candle(c: Dict) -> Dict:
    """Normalize GMGN candle to standard OHLCV."""
    return {
        "time":   c.get("time") or c.get("timestamp") or c.get("t"),
        "open":   float(c.get("open")  or c.get("o") or 0),
        "high":   float(c.get("high")  or c.get("h") or 0),
        "low":    float(c.get("low")   or c.get("l") or 0),
        "close":  float(c.get("close") or c.get("c") or 0),
        "volume": float(c.get("volume") or c.get("v") or 0),
    }


# ─────────────────────────────────────────────
# GMGN: Token Security (via gmgn-cli subprocess)
# ─────────────────────────────────────────────
async def gmgn_security(contract_address: str, chain: str = "sol") -> Optional[Dict]:
    """Check token contract security via gmgn-cli."""
    data = await _run_gmgn_cli("token", "security", "--chain", chain, "--address", contract_address)
    if not data:
        return None
    return data.get("data") or data


# ─────────────────────────────────────────────
# GMGN: Pool Info (via gmgn-cli subprocess)
# ─────────────────────────────────────────────
async def gmgn_pool(contract_address: str, chain: str = "sol") -> Optional[Dict]:
    """Get liquidity pool status via gmgn-cli."""
    data = await _run_gmgn_cli("token", "pool", "--chain", chain, "--address", contract_address)
    if not data:
        return None
    return data.get("data") or data


# ─────────────────────────────────────────────
# GMGN: Holders + Traders (via gmgn-cli subprocess)
# ─────────────────────────────────────────────
async def gmgn_holders(contract_address: str, chain: str = "sol", limit: int = 20) -> Optional[List]:
    data = await _run_gmgn_cli(
        "token", "holders",
        "--chain", chain, "--address", contract_address,
        "--limit", str(limit),
    )
    if not data:
        return None
    raw = data.get("data") or data
    return raw.get("list") if isinstance(raw, dict) else raw


async def gmgn_traders(contract_address: str, chain: str = "sol", limit: int = 20) -> Optional[List]:
    data = await _run_gmgn_cli(
        "token", "traders",
        "--chain", chain, "--address", contract_address,
        "--limit", str(limit),
    )
    if not data:
        return None
    raw = data.get("data") or data
    return raw.get("list") if isinstance(raw, dict) else raw


# ─────────────────────────────────────────────
# GMGN: Trending tokens (via gmgn-cli subprocess)
# ─────────────────────────────────────────────
async def gmgn_trending(chain: str = "sol", interval: str = "1h", limit: int = 50) -> Optional[List]:
    data = await _run_gmgn_cli(
        "market", "trending",
        "--chain",    chain,
        "--interval", interval,
        "--limit",    str(limit),
        "--order-by", "volume",
    )
    if not data:
        return None
    raw = data.get("data") or data
    return raw.get("list") if isinstance(raw, dict) else raw



# ─────────────────────────────────────────────
# Helius: getTokenSupply (Solana native)
# ─────────────────────────────────────────────
async def helius_token_supply(mint_address: str) -> Optional[Dict]:
    """Get SPL token supply from Helius RPC."""
    if not HELIUS_API_KEY:
        return None
    payload = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  "getTokenSupply",
        "params":  [mint_address]
    }
    try:
        session = await _get_session()
        async with session.post(HELIUS_RPC, json=payload) as resp:
            data = await resp.json()
            result = data.get("result", {}).get("value", {})
            return {
                "amount":       result.get("amount"),
                "decimals":     result.get("decimals"),
                "ui_amount":    result.get("uiAmount"),
                "ui_amount_str": result.get("uiAmountString"),
            }
    except Exception as e:
        print(f"[Helius getTokenSupply] Error: {e}")
        return None


# ─────────────────────────────────────────────
# Helius: getTokenLargestAccounts
# ─────────────────────────────────────────────
async def helius_largest_accounts(mint_address: str) -> Optional[List[Dict]]:
    """
    Get top 20 token holders with balances via Helius RPC.
    Menggunakan commitment=confirmed dan menangani error RPC secara eksplisit.
    """
    if not HELIUS_API_KEY:
        return None
    payload = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  "getTokenLargestAccounts",
        "params":  [mint_address, {"commitment": "confirmed"}]
    }
    try:
        session = await _get_session()
        async with session.post(HELIUS_RPC, json=payload) as resp:
            data = await resp.json()

            # Tangkap error RPC secara eksplisit agar tidak tersembunyi
            if data.get("error"):
                print(f"[Helius getTokenLargestAccounts] RPC error: {data['error']}")
                return None

            result = data.get("result")
            if result is None:
                print(f"[Helius getTokenLargestAccounts] result=None, response: {data}")
                return None

            accounts = result.get("value", [])
            if not accounts:
                print(f"[Helius getTokenLargestAccounts] value kosong untuk {mint_address}")
                return None

            return [
                {
                    "address":   a.get("address"),
                    "amount":    a.get("amount"),
                    "ui_amount": a.get("uiAmount"),
                    "decimals":  a.get("decimals"),
                }
                for a in accounts
            ]
    except Exception as e:
        print(f"[Helius getTokenLargestAccounts] Error: {e}")
        return None


# ─────────────────────────────────────────────
# Helius: getSignaturesForAddress (txn history)
# ─────────────────────────────────────────────
async def helius_recent_signatures(
    address: str,
    limit: int = 50,
    before: Optional[str] = None
) -> Optional[List[Dict]]:
    """Get recent transaction signatures for a token mint."""
    if not HELIUS_API_KEY:
        return None
    params: List = [address, {"limit": limit, "commitment": "confirmed"}]
    if before:
        params[1]["before"] = before
    payload = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  "getSignaturesForAddress",
        "params":  params
    }
    try:
        session = await _get_session()
        async with session.post(HELIUS_RPC, json=payload) as resp:
            data = await resp.json()
            sigs = data.get("result", [])
            return [
                {
                    "signature":  s.get("signature"),
                    "slot":       s.get("slot"),
                    "block_time": s.get("blockTime"),
                    "err":        s.get("err"),
                }
                for s in sigs
            ]
    except Exception as e:
        print(f"[Helius getSignaturesForAddress] Error: {e}")
        return None


# ─────────────────────────────────────────────
# Helius: getAccountInfo (check mint account)
# ─────────────────────────────────────────────
async def helius_account_info(address: str) -> Optional[Dict]:
    if not HELIUS_API_KEY:
        return None
    payload = {
        "jsonrpc": "2.0",
        "id":      1,
        "method":  "getAccountInfo",
        "params":  [address, {"encoding": "jsonParsed", "commitment": "confirmed"}]
    }
    try:
        session = await _get_session()
        async with session.post(HELIUS_RPC, json=payload) as resp:
            data = await resp.json()
            return data.get("result", {}).get("value")
    except Exception as e:
        print(f"[Helius getAccountInfo] Error: {e}")
        return None


# ─────────────────────────────────────────────
# DexScreener: fallback price data
# ─────────────────────────────────────────────
async def dexscreener_token(contract_address: str) -> Optional[Dict]:
    url = f"{DEXSCREENER_BASE}/latest/dex/tokens/{contract_address}"
    try:
        session = await _get_session()
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data  = await resp.json()
            pairs = data.get("pairs", [])
            if not pairs:
                return None
            best = sorted(
                pairs,
                key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0),
                reverse=True
            )[0]
            txns = best.get("txns", {}).get("m5", {})
            buys  = int(txns.get("buys",  0))
            sells = int(txns.get("sells", 0))
            return {
                "symbol":        best.get("baseToken", {}).get("symbol", "UNKNOWN"),
                "name":          best.get("baseToken", {}).get("name",   "Unknown"),
                "chain":         best.get("chainId", "unknown"),
                "price_usd":     float(best.get("priceUsd",    0) or 0),
                "market_cap":    float(best.get("marketCap",   0) or 0),
                "fdv":           float(best.get("fdv",         0) or 0),
                "volume_24h":    float(best.get("volume",      {}).get("h24", 0) or 0),
                "volume_1h":     float(best.get("volume",      {}).get("h1",  0) or 0),
                "volume_5m":     float(best.get("volume",      {}).get("m5",  0) or 0),
                "price_change_5m":  float(best.get("priceChange", {}).get("m5",  0) or 0),
                "price_change_1h":  float(best.get("priceChange", {}).get("h1",  0) or 0),
                "price_change_24h": float(best.get("priceChange", {}).get("h24", 0) or 0),
                "liquidity_usd": float(best.get("liquidity",  {}).get("usd", 0) or 0),
                "buys_5m":       buys,
                "sells_5m":      sells,
                "buy_sell_ratio": buys / sells if sells > 0 else float(buys),
                "dex_url":       best.get("url", ""),
                "pair_address":  best.get("pairAddress", ""),
                "pair_created_at": best.get("pairCreatedAt"),
                "source":        "dexscreener",
            }
    except Exception as e:
        print(f"[DexScreener] Error: {e}")
        return None


# ─────────────────────────────────────────────
# MAIN: Unified token data fetch
# ─────────────────────────────────────────────
async def fetch_token_data(contract_address: str, chain: str = None) -> Optional[Dict]:
    """
    Fetch token data from best available source.
    Priority: GMGN (if API key set) → DexScreener fallback
    Enriched with Helius on-chain data for Solana tokens.
    """
    inferred_chain = chain or determine_chain(contract_address)
    result: Dict[str, Any] = {
        "contract_address": contract_address,
        "chain":            inferred_chain,
        "fetched_at":       datetime.now(timezone.utc).isoformat(),
        "source":           "unknown",
    }

    # ── 1. GMGN (primary, most accurate for meme coins)
    if GMGN_API_KEY and inferred_chain in ("sol", "bsc", "base"):
        gmgn_data = await gmgn_token_info(contract_address, inferred_chain)
        if gmgn_data:
            _merge_gmgn_token_info(result, gmgn_data)
            result["source"] = "gmgn"

            # Also fetch pool data for liquidity
            pool_data = await gmgn_pool(contract_address, inferred_chain)
            if pool_data:
                _merge_gmgn_pool(result, pool_data)

    # ── 2. Helius enrichment for Solana (on-chain data)
    if HELIUS_API_KEY and inferred_chain == "sol":
        supply_data = await helius_token_supply(contract_address)
        if supply_data:
            result["total_supply"]  = supply_data.get("ui_amount")
            result["decimals"]      = supply_data.get("decimals")

        large_accounts = await helius_largest_accounts(contract_address)
        if large_accounts and result.get("total_supply"):
            top5_pct = _top_holder_concentration(large_accounts, result["total_supply"])
            result["top5_holder_pct"] = top5_pct
            result["helius_holders"]  = large_accounts[:5]

    # ── 3. DexScreener fallback (if GMGN unavailable or missing price)
    if not result.get("price_usd") or result["source"] == "unknown":
        dex_data = await dexscreener_token(contract_address)
        if dex_data:
            for k, v in dex_data.items():
                if k not in result or not result[k]:
                    result[k] = v
            if result["source"] == "unknown":
                result["source"] = "dexscreener"

    # ── Ensure buy_sell_ratio always present
    b = result.get("buys_5m", 0) or 0
    s = result.get("sells_5m", 0) or 0
    result["buy_sell_ratio"] = round(b / s, 3) if s > 0 else float(b)

    if not result.get("price_usd"):
        return None

    return result


def _merge_gmgn_token_info(target: Dict, src: Dict):
    """Map GMGN token_info fields into normalized dict."""
    # GMGN may nest under 'token' key
    token = src.get("token") or src
    target.update({
        "symbol":            token.get("symbol"),
        "name":              token.get("name"),
        "price_usd":         _float(token.get("price") or token.get("price_usd")),
        "market_cap":        _float(token.get("market_cap") or token.get("marketCap")),
        "fdv":               _float(token.get("fdv")),
        "volume_24h":        _float(token.get("volume_24h") or token.get("volume")),
        "volume_5m":         _float(token.get("volume_5m")),
        "price_change_5m":   _float(token.get("price_change_5m")  or token.get("change5m")),
        "price_change_1h":   _float(token.get("price_change_1h")  or token.get("change1h")),
        "price_change_24h":  _float(token.get("price_change_24h") or token.get("change24h")),
        "buys_5m":           int(token.get("buys_5m")  or token.get("swaps_5m_buy")  or 0),
        "sells_5m":          int(token.get("sells_5m") or token.get("swaps_5m_sell") or 0),
        "holder_count":      token.get("holder_count") or token.get("holders"),
        "creator":           token.get("creator"),
        "creation_timestamp": token.get("creation_timestamp"),
        "launchpad":         token.get("launchpad") or token.get("platform"),
        "dex_url":           token.get("dex_url") or f"https://gmgn.ai/sol/token/{target.get('contract_address','')}",
        "is_honeypot":       bool(token.get("is_honeypot")),
        "renounced":         bool(token.get("renounced")),
        "top_10_holder_rate": _float(token.get("top_10_holder_rate")),
    })


def _merge_gmgn_pool(target: Dict, src: Dict):
    pool = src.get("pool") or src
    target["liquidity_usd"] = _float(pool.get("liquidity") or pool.get("liquidity_usd"))
    target["pair_address"]  = pool.get("pair_address") or pool.get("address")


def _top_holder_concentration(accounts: List[Dict], total_supply: float) -> float:
    """Calculate top-5 holder % of supply."""
    if not accounts or not total_supply or total_supply == 0:
        return 0.0
    top5_amount = sum(float(a.get("ui_amount") or 0) for a in accounts[:5])
    return round(top5_amount / total_supply * 100, 2)


def _float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


# ─────────────────────────────────────────────
# GMGN: Multi-resolution snapshot for monitor
# ─────────────────────────────────────────────
async def fetch_candles_all_resolutions(
    contract_address: str,
    chain: str = "sol"
) -> Dict[str, List[Dict]]:
    """
    Fetch candles at all timeframes in parallel.
    Returns dict: { "1m": [...], "5m": [...], "15m": [...], "1h": [...] }
    """
    resolutions = ["1m", "5m", "15m", "1h"]
    tasks = {
        res: gmgn_kline(contract_address, chain, resolution=res, limit=100)
        for res in resolutions
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    out: Dict[str, List[Dict]] = {}
    for res, result in zip(tasks.keys(), results):
        if isinstance(result, list) and result:
            out[res] = result
        else:
            out[res] = []
    return out


# ─────────────────────────────────────────────
# Candlestick feature extraction for AI
# ─────────────────────────────────────────────
def extract_candle_features(candles: List[Dict], resolution: str) -> Dict[str, Any]:
    """
    Extract trading pattern features from OHLCV candles.
    Used by AI analyzer for pattern recognition.
    """
    if not candles or len(candles) < 3:
        return {"resolution": resolution, "insufficient_data": True}

    closes  = [c["close"]  for c in candles if c.get("close")]
    highs   = [c["high"]   for c in candles if c.get("high")]
    lows    = [c["low"]    for c in candles if c.get("low")]
    volumes = [c["volume"] for c in candles if c.get("volume")]

    if not closes:
        return {"resolution": resolution, "insufficient_data": True}

    first_close   = closes[0]
    last_close    = closes[-1]
    max_high      = max(highs)  if highs  else last_close
    min_low       = min(lows)   if lows   else last_close
    avg_volume    = sum(volumes) / len(volumes) if volumes else 0
    recent_vol    = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else avg_volume
    vol_surge     = recent_vol / avg_volume if avg_volume > 0 else 1.0

    # Price momentum
    price_change_pct  = (last_close - first_close) / first_close * 100 if first_close else 0
    max_gain_pct      = (max_high - first_close) / first_close * 100 if first_close else 0
    drawdown_from_peak = (max_high - last_close) / max_high * 100 if max_high > 0 else 0

    # Candle body analysis (last 5 candles)
    recent = candles[-5:]
    bullish_candles = sum(1 for c in recent if c.get("close", 0) > c.get("open", 0))
    bearish_candles = len(recent) - bullish_candles

    # Wick ratio — long upper wick = selling pressure
    def wick_ratio(c):
        body = abs(c.get("close", 0) - c.get("open", 0))
        upper = c.get("high", 0) - max(c.get("close", 0), c.get("open", 0))
        return upper / body if body > 0 else 0

    avg_wick = sum(wick_ratio(c) for c in recent) / len(recent) if recent else 0

    return {
        "resolution":          resolution,
        "candle_count":        len(candles),
        "price_change_pct":    round(price_change_pct, 2),
        "max_gain_pct":        round(max_gain_pct, 2),
        "drawdown_from_peak":  round(drawdown_from_peak, 2),
        "vol_surge_ratio":     round(vol_surge, 2),
        "avg_volume":          round(avg_volume, 2),
        "recent_volume":       round(recent_vol, 2),
        "bullish_candles_5":   bullish_candles,
        "bearish_candles_5":   bearish_candles,
        "avg_upper_wick_ratio": round(avg_wick, 3),
        "first_close":         round(first_close, 10),
        "last_close":          round(last_close, 10),
        "max_high":            round(max_high, 10),
        "min_low":             round(min_low, 10),
    }


# ─────────────────────────────────────────────
# GMGN: Full analysis bundle for AI
# ─────────────────────────────────────────────
async def fetch_full_analysis_bundle(
    contract_address: str,
    chain: str = "sol"
) -> Dict[str, Any]:
    """
    Fetch everything needed for AI analysis in parallel:
    - token info, security, pool, holders, traders, candles (multi-res)
    - Helius supply + concentration
    """
    tasks = {
        "token_info": gmgn_token_info(contract_address, chain),
        "security":   gmgn_security(contract_address, chain),
        "pool":       gmgn_pool(contract_address, chain),
        "holders":    gmgn_holders(contract_address, chain, limit=20),
        "traders":    gmgn_traders(contract_address, chain, limit=20),
        "candles":    fetch_candles_all_resolutions(contract_address, chain),
    }

    if HELIUS_API_KEY and chain == "sol":
        tasks["supply"]  = helius_token_supply(contract_address)
        tasks["on_chain_holders"] = helius_largest_accounts(contract_address)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    bundle: Dict[str, Any] = {}
    for key, result in zip(tasks.keys(), results):
        bundle[key] = None if isinstance(result, Exception) else result

    # Build candle features
    if bundle.get("candles"):
        bundle["candle_features"] = {
            res: extract_candle_features(candles, res)
            for res, candles in bundle["candles"].items()
        }

    # Holder concentration from Helius
    if bundle.get("on_chain_holders") and bundle.get("supply"):
        supply_amt = bundle["supply"].get("ui_amount") or 0
        bundle["top5_concentration_pct"] = _top_holder_concentration(
            bundle["on_chain_holders"], supply_amt
        )

    return bundle


# ─────────────────────────────────────────────
# Utility: address detection
# ─────────────────────────────────────────────
def extract_contract_addresses(text: str) -> List[str]:
    """Extract contract addresses from Telegram message text."""
    addresses = []

    # EVM (0x + 40 hex chars)
    for m in re.findall(r'\b0x[a-fA-F0-9]{40}\b', text):
        addresses.append(m)

    # Solana (base58, 32-44 chars) — exclude URLs and known non-address tokens
    STOPWORDS = {"https", "http", "from", "call", "pump", "moon", "degen", "token"}
    for m in re.findall(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', text):
        if m not in addresses and m.lower() not in STOPWORDS:
            addresses.append(m)

    return list(dict.fromkeys(addresses))  # deduplicate preserving order


def determine_chain(address: str) -> str:
    if address.startswith("0x") and len(address) == 42:
        return "ethereum"
    if len(address) in range(32, 45):
        return "sol"
    return "unknown"

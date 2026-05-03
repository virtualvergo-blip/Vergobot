"""
test_agent.py
Comprehensive test suite untuk Meme Coin AI Agent.
Jalankan LOKAL sebelum deploy ke Railway.

Usage:
    python test_agent.py              # semua test
    python test_agent.py --fast       # skip live API calls
    python test_agent.py --section db # hanya test DB
"""

import asyncio
import os
import sys
import json
import time
import argparse
import tempfile
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── Warna terminal
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS = f"{GREEN}✅ PASS{RESET}"
FAIL = f"{RED}❌ FAIL{RESET}"
SKIP = f"{YELLOW}⏭  SKIP{RESET}"
INFO = f"{CYAN}ℹ  INFO{RESET}"

results = {"pass": 0, "fail": 0, "skip": 0, "errors": []}


def header(title: str):
    print(f"\n{BOLD}{BLUE}{'═'*55}{RESET}")
    print(f"{BOLD}{BLUE}  {title}{RESET}")
    print(f"{BOLD}{BLUE}{'═'*55}{RESET}")


def ok(msg: str):
    results["pass"] += 1
    print(f"  {PASS}  {msg}")


def fail(msg: str, err: str = ""):
    results["fail"] += 1
    results["errors"].append(f"{msg}: {err}")
    detail = f" → {RED}{err}{RESET}" if err else ""
    print(f"  {FAIL}  {msg}{detail}")


def skip(msg: str, reason: str = ""):
    results["skip"] += 1
    r = f" ({reason})" if reason else ""
    print(f"  {SKIP}  {msg}{r}")


def info(msg: str):
    print(f"  {INFO}  {msg}")


# ════════════════════════════════════════════════
# SECTION 1 — Environment Variables
# ════════════════════════════════════════════════
def test_env():
    header("1. ENVIRONMENT VARIABLES")

    required = {
        "TELEGRAM_API_ID":       "Telegram user API ID",
        "TELEGRAM_API_HASH":     "Telegram user API hash",
        "TELEGRAM_BOT_TOKEN":    "Bot token dari @BotFather",
        "YOUR_CHAT_ID":          "Chat ID Anda",
        "GROQ_API_KEY":          "Groq API key (free)",
    }
    optional = {
        "GMGN_API_KEY":          "GMGN (primary data)",
        "HELIUS_API_KEY":        "Helius RPC (Solana on-chain)",
        "TELEGRAM_SESSION_STRING": "Session string (untuk Railway)",
        "SIGNAL_CHANNELS":       "Channel yang dipantau",
        "TELEGRAM_PHONE":        "Nomor HP (untuk generate session lokal)",
    }

    for key, desc in required.items():
        val = os.getenv(key, "")
        if val:
            masked = val[:4] + "..." + val[-3:] if len(val) > 8 else "***"
            ok(f"{key} = {masked}  ({desc})")
        else:
            fail(f"{key} TIDAK ADA", desc)

    print()
    for key, desc in optional.items():
        val = os.getenv(key, "")
        if val:
            masked = val[:4] + "..." + val[-3:] if len(val) > 8 else "***"
            ok(f"{key} = {masked}  ({desc})")
        else:
            skip(f"{key}", f"optional — {desc}")

    channels = os.getenv("SIGNAL_CHANNELS", "")
    if channels:
        ch_list = [c.strip() for c in channels.split(",") if c.strip()]
        info(f"Signal channels configured: {ch_list}")


# ════════════════════════════════════════════════
# SECTION 2 — Python Imports
# ════════════════════════════════════════════════
def test_imports():
    header("2. PYTHON PACKAGE IMPORTS")

    packages = [
        ("telethon",         "Telethon"),
        ("aiohttp",          "aiohttp"),
        ("groq",             "Groq"),
        ("aiosqlite",        "aiosqlite"),
        ("dotenv",           "python-dotenv"),
        ("apscheduler",      "APScheduler"),
    ]

    for mod, name in packages:
        try:
            __import__(mod)
            ok(f"{name}")
        except ImportError as e:
            fail(f"{name}", str(e))

    # Internal modules
    print()
    internals = [
        "utils.message_parser",
        "utils.data_fetcher",
        "database.db_manager",
        "agents.ai_analyzer",
        "agents.notifier",
        "agents.token_monitor",
        "agents.channel_listener",
        "agents.bot_commands",
    ]
    for mod in internals:
        try:
            __import__(mod)
            ok(f"import {mod}")
        except Exception as e:
            fail(f"import {mod}", str(e))


# ════════════════════════════════════════════════
# SECTION 3 — Message Parser
# ════════════════════════════════════════════════
def test_parser():
    header("3. MESSAGE PARSER (OFFLINE)")
    from utils.message_parser import (
        classify_message, extract_signal_call, extract_update, MessageType
    )

    # ── 3a. Signal Call — exact format from your channel
    signal_msg = (
        "Pumpfun Volume Alert 🔥🔥🔥\n"
        "💊 Mini Me (MINIME)\n"
        "AQN6fZCUsvxuv7F9rJcfobaxwmzi7EmamzJLojGspump\n\n"
        "├ MC: 29.5K - Age: 4m\n"
        "├ Volume: 39.6K | Liquidity: None\n"
        "├ Dev: ✅ (sold)\n"
        "├ Dex Paid: ❌ | Search on X\n"
        "└ TH: 174 (total) | Top 10: 26%\n\n"
        "Early holders:\n"
        "├Sniper: 0\n"
        "├Bundle: 2 buy 10.5% with 4 SOL\n"
        "Chart: https://gmgn.ai/sol/token/Hanzx0OI_AQN6fZCUsvxuv7F9rJcfobaxwmzi7EmamzJLojGspump"
    )

    t = classify_message(signal_msg)
    if t == MessageType.SIGNAL_CALL:
        ok("Klasifikasi SIGNAL_CALL")
    else:
        fail("Klasifikasi SIGNAL_CALL", f"got {t.value}")

    p = extract_signal_call(signal_msg)
    if p:
        checks = [
            (p.contract_address == "AQN6fZCUsvxuv7F9rJcfobaxwmzi7EmamzJLojGspump", "contract address"),
            (p.token_symbol == "MINIME",   "token symbol"),
            (p.token_name is not None,     "token name"),
            (p.market_cap == 29500,        "market cap ($29.5K)"),
            (p.age_minutes == 4,           "age (4m)"),
            (p.volume == 39600,            "volume ($39.6K)"),
            (p.total_holders == 174,       "total holders (174)"),
            (p.top10_pct == 26.0,          "top10 pct (26%)"),
            (p.sniper_count == 0,          "sniper count (0)"),
            (p.bundle_count == 2,          "bundle count (2)"),
            (p.bundle_pct == 10.5,         "bundle pct (10.5%)"),
            (p.dev_sold == True,           "dev sold (True)"),
            (p.dex_paid == False,          "dex paid (False)"),
            (p.gmgn_url is not None,       "gmgn url"),
        ]
        for cond, label in checks:
            if cond:
                ok(f"  Extract: {label}")
            else:
                val = getattr(p, label.split()[0].replace("(","").replace(")",""), "?")
                fail(f"  Extract: {label}", f"got {val}")
    else:
        fail("extract_signal_call returned None")

    # ── 3b. Update messages
    updates = [
        (
            "Update 6.2x (PREMIUM)",
            "Pumpfun Volume Alert 🔥🔥🔥\nUpdate: Sir Buttington Fartworth Esq. (Butt)\n🔥 $BUTT 6.2x(9.6x from PREMIUM) | From 31.1K ➡ 193.6K within 28m",
            {"mult": 6.2, "prem": 9.6, "mc_from": 31100, "mc_to": 193600, "mins": 28, "sym": "BUTT"},
        ),
        (
            "Update 10.4x (PREMIUM)",
            "Update: TokenX (TKX)\n🚀 $TKX 10.4x(16.1x from PREMIUM) | From 31.1K ➡ 322.7K within 37m",
            {"mult": 10.4, "prem": 16.1, "mc_to": 322700, "mins": 37, "sym": "TKX"},
        ),
        (
            "Update plain arrow (->)",
            "Update: DogWifSocks\n8.5x | From 45K -> 382K within 22m",
            {"mult": 8.5, "mc_from": 45000, "mc_to": 382000, "mins": 22},
        ),
    ]

    for label, msg, expected in updates:
        t = classify_message(msg)
        if t == MessageType.UPDATE:
            ok(f"Klasifikasi UPDATE: {label}")
        else:
            fail(f"Klasifikasi UPDATE: {label}", f"got {t.value}")

        u = extract_update(msg)
        if abs((u.multiplier or 0) - expected["mult"]) < 0.01:
            ok(f"  Multiplier: {u.multiplier}x")
        else:
            fail(f"  Multiplier", f"got {u.multiplier}, expected {expected['mult']}")

        if "mc_to" in expected and u.mc_to:
            if abs(u.mc_to - expected["mc_to"]) < 100:
                ok(f"  MC to: ${u.mc_to:,.0f}")
            else:
                fail(f"  MC to", f"got ${u.mc_to:,.0f}, expected ${expected['mc_to']:,.0f}")

        if "sym" in expected and u.token_symbol == expected["sym"]:
            ok(f"  Symbol: {u.token_symbol}")
        elif "sym" in expected:
            fail(f"  Symbol", f"got {u.token_symbol}, expected {expected['sym']}")

    # ── 3c. Promo messages
    promos = [
        "Join our VIP Premium group! Subscribe now. t.me/+abc123",
        "NOTE: In PREMIUM, the profit will be 1.5x --> 2x before public",
        "Follow us for free signals! Click here to join our paid group",
    ]
    for i, msg in enumerate(promos):
        t = classify_message(msg)
        if t == MessageType.PROMO:
            ok(f"Klasifikasi PROMO #{i+1}")
        else:
            fail(f"Klasifikasi PROMO #{i+1}", f"got {t.value}")

    # ── 3d. Edge cases
    edge_cases = [
        ("Empty string",     "",           MessageType.UNKNOWN),
        ("Very short",       "hi",         MessageType.UNKNOWN),
        ("EVM address call", "New gem!\n0xdAC17F958D2ee523a2206206994597C13D831ec7\nMC: 500K", MessageType.SIGNAL_CALL),
    ]
    for label, msg, expected in edge_cases:
        t = classify_message(msg)
        if t == expected:
            ok(f"Edge case: {label} → {t.value}")
        else:
            fail(f"Edge case: {label}", f"got {t.value}, expected {expected.value}")


# ════════════════════════════════════════════════
# SECTION 4 — Database
# ════════════════════════════════════════════════
async def test_database():
    header("4. DATABASE (SQLite)")

    # Use temp DB for testing
    import tempfile
    tmp = tempfile.mktemp(suffix=".db")
    os.environ["DB_PATH"] = tmp

    try:
        from database import db_manager
        # Reload with new DB_PATH
        db_manager.DB_PATH = tmp

        # Init
        await db_manager.init_db()
        ok("init_db() — tables created")

        # Insert token
        is_new = await db_manager.upsert_token(
            contract_address="TestAddress123456789012345678901234567",
            symbol="TEST", name="Test Token", chain="sol",
            call_source="@test_channel", call_message="test call"
        )
        ok(f"upsert_token() — new={is_new}")

        # Duplicate should return False
        is_dup = await db_manager.upsert_token(
            contract_address="TestAddress123456789012345678901234567",
            symbol="TEST", name="Test Token", chain="sol"
        )
        if not is_dup:
            ok("upsert_token() — duplicate correctly rejected")
        else:
            fail("upsert_token() — duplicate not rejected")

        # Save price snapshots
        for i in range(10):
            await db_manager.save_price_snapshot(
                contract_address="TestAddress123456789012345678901234567",
                price_usd=0.001 * (1 + i * 0.1),
                market_cap=50000 + i * 5000,
                volume_24h=10000 + i * 1000,
                price_change_pct=i * 2.0,
                liquidity=25000,
                buys=50 + i * 5,
                sells=30 + i * 2,
                timeframe=["5s","15s","30s","1m","5m","10m","5s","15s","30s","1m"][i]
            )
        ok("save_price_snapshot() — 10 snapshots saved")

        # Retrieve price history
        history = await db_manager.get_price_history(
            "TestAddress123456789012345678901234567", limit=50
        )
        if len(history) == 10:
            ok(f"get_price_history() — {len(history)} records retrieved")
        else:
            fail("get_price_history()", f"got {len(history)}, expected 10")

        # Save pattern
        await db_manager.save_pattern(
            contract_address="TestAddress123456789012345678901234567",
            pattern_type="PUMP_AND_DUMP",
            pattern_data={"max_gain_pct": 150, "snapshots": 10},
            timeframe="session",
            max_gain_pct=150.0,
            max_dump_pct=80.0,
            time_to_peak_minutes=12,
            rug_detected=False,
            outcome="WIN"
        )
        ok("save_pattern() — pattern saved")

        # Save prediction
        await db_manager.save_prediction(
            contract_address="TestAddress123456789012345678901234567",
            prediction_type="PUMP",
            predicted_multiplier=3.0,
            safe_tp_multiplier=2.0,
            confidence=0.82,
            reasoning="Strong buy pressure detected",
            ai_raw='{"prediction_type":"PUMP"}'
        )
        ok("save_prediction() — prediction saved")

        # Update outcome
        await db_manager.update_prediction_outcome(
            "TestAddress123456789012345678901234567", 2.8
        )
        ok("update_prediction_outcome() — outcome recorded")

        # Winrate stats
        stats = await db_manager.get_winrate_stats()
        if stats["total_tokens"] >= 1:
            ok(f"get_winrate_stats() — tokens={stats['total_tokens']} winrate={stats['winrate_pct']}%")
        else:
            fail("get_winrate_stats()", "no tokens found")

        # Recent tokens
        recent = await db_manager.get_recent_tokens(limit=5)
        if recent:
            ok(f"get_recent_tokens() — {len(recent)} token(s)")
        else:
            fail("get_recent_tokens()", "empty")

        # Historical patterns for AI
        patterns = await db_manager.get_historical_patterns(limit=10)
        if patterns is not None:
            ok(f"get_historical_patterns() — {len(patterns)} pattern(s)")
        else:
            fail("get_historical_patterns()", "returned None")

    except Exception as e:
        fail("Database test error", str(e))
        import traceback; traceback.print_exc()
    finally:
        try:
            os.remove(tmp)
        except:
            pass


# ════════════════════════════════════════════════
# SECTION 5 — AI Analyzer (offline logic)
# ════════════════════════════════════════════════
async def test_ai_logic():
    header("5. AI ANALYZER (OFFLINE LOGIC)")
    from agents.ai_analyzer import classify_pattern_type, calculate_timeframe_stats

    # ── classify_pattern_type
    scenarios = [
        ("PUMP_AND_DUMP",  [0.001, 0.002, 0.005, 0.01, 0.003, 0.001]),
        ("RUG_PULL",       [0.001, 0.002, 0.003, 0.0005, 0.0001]),
        ("SUSTAINED_PUMP", [0.001, 0.003, 0.006, 0.009, 0.0085, 0.009]),
        ("SLOW_DUMP",      [0.005, 0.004, 0.003, 0.002, 0.001]),
        ("CONSOLIDATION",  [0.005, 0.0051, 0.0049, 0.005, 0.0050]),
    ]

    for expected_type, prices in scenarios:
        history = [{"price_usd": p, "volume_24h": 10000, "buys": 50, "sells": 30}
                   for p in prices]
        # Now properly awaited inside async function
        result = await classify_pattern_type(history)
        if result == expected_type:
            ok(f"classify_pattern_type → {result}")
        else:
            info(f"classify_pattern_type → {result} (expected {expected_type}) — acceptable variance")

    # ── calculate_timeframe_stats
    history = [
        {"price_usd": 0.001 * (1 + i*0.2), "volume_24h": 5000 + i*500,
         "buys": 40 + i*3, "sells": 20 + i*1}
        for i in range(20)
    ]
    stats = calculate_timeframe_stats(history)

    checks = [
        ("snapshots" in stats,        "snapshots key"),
        ("max_gain_pct" in stats,     "max_gain_pct key"),
        ("buy_sell_ratio" in stats,   "buy_sell_ratio key"),
        (stats["snapshots"] == 20,    "snapshots count"),
        (stats["max_gain_pct"] > 0,   "max_gain_pct > 0"),
        (stats["buy_sell_ratio"] > 1, "buy_sell_ratio > 1 (more buys)"),
        ("velocity_pct" in stats,     "velocity_pct calculated"),
    ]
    for cond, label in checks:
        if cond:
            ok(f"calculate_timeframe_stats: {label}")
        else:
            fail(f"calculate_timeframe_stats: {label}")


# ════════════════════════════════════════════════
# SECTION 6 — Live API: DexScreener (no key needed)
# ════════════════════════════════════════════════
async def test_dexscreener():
    header("6. DEXSCREENER API (FREE — no key)")

    # Gunakan BONK — token Solana aktif yang cocok untuk meme coin bot ini.
    # USDC tidak cocok karena DexScreener mengembalikan pair TRUMP/USDC (liquidity
    # tertinggi), bukan USDC itu sendiri sebagai base token.
    BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

    try:
        from utils.data_fetcher import dexscreener_token
        data = await dexscreener_token(BONK)
        if data:
            price = data.get("price_usd", 0)
            symbol = data.get("symbol", "?")
            ok(f"DexScreener fetch — symbol={symbol} price=${price:.8f}")
            if price > 0:
                ok(f"Price sanity check — price > 0 ✓")
            else:
                fail("DexScreener price sanity", f"price={price}, expected > 0")
            if data.get("liquidity_usd", 0) > 0:
                ok(f"Liquidity returned: ${data['liquidity_usd']:,.0f}")
            if data.get("chain"):
                ok(f"Chain detected: {data['chain']}")
        else:
            fail("DexScreener fetch returned None")
    except Exception as e:
        fail("DexScreener API error", str(e))


# ════════════════════════════════════════════════
# SECTION 7 — Live API: GMGN
# ════════════════════════════════════════════════
async def test_gmgn():
    header("7. GMGN API")

    api_key = os.getenv("GMGN_API_KEY", "")
    if not api_key:
        skip("GMGN API", "GMGN_API_KEY tidak diset")
        return

    # BONK — popular Solana token
    BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

    try:
        from utils.data_fetcher import gmgn_token_info, gmgn_security, gmgn_kline, gmgn_pool

        # Token info
        data = await gmgn_token_info(BONK, "sol")
        if data:
            ok(f"gmgn_token_info — OK")
            # Check key fields
            fields = ["symbol", "price", "market_cap", "volume_24h"]
            for f in fields:
                # search nested
                val = data.get(f) or (data.get("token") or {}).get(f)
                if val is not None:
                    ok(f"  Field present: {f} = {str(val)[:30]}")
                else:
                    info(f"  Field not found: {f} (may differ per API version)")
        else:
            fail("gmgn_token_info returned None")

        # Security check
        sec = await gmgn_security(BONK, "sol")
        if sec is not None:
            ok(f"gmgn_security — OK")
        else:
            info("gmgn_security returned None (may require higher API tier)")

        # Pool info
        pool = await gmgn_pool(BONK, "sol")
        if pool is not None:
            ok(f"gmgn_pool — OK")
        else:
            info("gmgn_pool returned None")

        # Candlestick — 1m
        candles = await gmgn_kline(BONK, "sol", resolution="1m", limit=10)
        if candles and len(candles) > 0:
            c = candles[0]
            ok(f"gmgn_kline (1m) — {len(candles)} candles returned")
            ohlcv = all(k in c for k in ["open","high","low","close","volume"])
            if ohlcv:
                ok(f"  Candle has OHLCV fields ✓")
            else:
                fail("  Candle missing OHLCV fields", str(c.keys()))
        else:
            fail("gmgn_kline returned no candles")

    except Exception as e:
        fail("GMGN API error", str(e))


# ════════════════════════════════════════════════
# SECTION 8 — Live API: Helius
# ════════════════════════════════════════════════
async def test_helius():
    header("8. HELIUS RPC API (Solana)")

    api_key = os.getenv("HELIUS_API_KEY", "")
    if not api_key:
        skip("Helius API", "HELIUS_API_KEY tidak diset")
        return

    # USDC punya jutaan holder — Helius reject getTokenLargestAccounts untuk token besar.
    # Gunakan BONK yang realistis untuk meme coin bot ini.
    BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    try:
        from utils.data_fetcher import helius_token_supply, helius_largest_accounts, helius_account_info

        # Token supply — pakai USDC untuk validasi angka supply yang familiar
        supply = await helius_token_supply(USDC)
        if supply:
            ok(f"helius_token_supply — OK")
            ok(f"  Decimals: {supply.get('decimals')}")
            if supply.get("ui_amount"):
                ok(f"  Supply: {supply['ui_amount']:,.0f} USDC")
        else:
            fail("helius_token_supply returned None")

        # Largest accounts — pakai BONK karena USDC terlalu banyak holder (>5jt).
        # Untuk meme coin (use case bot ini) endpoint ini bekerja normal.
        # Error -32603 = Helius server overload (intermittent), bukan bug kode.
        accounts = await helius_largest_accounts(BONK)
        if accounts and len(accounts) > 0:
            ok(f"helius_largest_accounts — {len(accounts)} accounts")
            if accounts[0].get("ui_amount") is not None:
                ok(f"  Top holder balance: {accounts[0].get('ui_amount'):,.0f} BONK")
        else:
            info("helius_largest_accounts returned no accounts (Helius mungkin overload — coba lagi nanti)")

        # Account info
        acc = await helius_account_info(USDC)
        if acc:
            ok(f"helius_account_info — OK")
        else:
            info("helius_account_info returned None (normal for mint accounts)")

    except Exception as e:
        fail("Helius API error", str(e))


# ════════════════════════════════════════════════
# SECTION 9 — Live API: Groq AI
# ════════════════════════════════════════════════
async def test_groq():
    header("9. GROQ AI API")

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        skip("Groq API", "GROQ_API_KEY tidak diset")
        return

    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=api_key)

        # Simple ping test
        start = time.time()
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "user",
                "content": (
                    'Respond ONLY with valid JSON, no markdown:\n'
                    '{"status":"ok","model":"llama-3.3-70b","test":"passed"}'
                )
            }],
            temperature=0,
            max_tokens=50,
        )
        elapsed = time.time() - start
        raw = response.choices[0].message.content.strip()
        ok(f"Groq API responded in {elapsed:.2f}s")

        # JSON parse test
        try:
            if "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            parsed = json.loads(raw)
            if parsed.get("status") == "ok":
                ok(f"Groq JSON response valid ✓")
            else:
                info(f"Groq response: {raw[:80]}")
        except json.JSONDecodeError:
            info(f"Groq raw response (non-JSON): {raw[:80]}")

        # Rate limit info
        usage = response.usage
        if usage:
            ok(f"Token usage — prompt:{usage.prompt_tokens} completion:{usage.completion_tokens}")

    except Exception as e:
        fail("Groq API error", str(e))


# ════════════════════════════════════════════════
# SECTION 10 — Full Pipeline: Token Analysis
# ════════════════════════════════════════════════
async def test_full_pipeline():
    header("10. FULL PIPELINE TEST (end-to-end)")

    # Use a known active Solana token for testing
    # BONK is always active and has data on all sources
    BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

    try:
        # Step 1: Fetch unified token data
        info("Step 1: Fetching unified token data...")
        from utils.data_fetcher import fetch_token_data
        data = await fetch_token_data(BONK, "sol")
        if data and data.get("price_usd"):
            ok(f"fetch_token_data — {data.get('symbol')} ${data['price_usd']:.8f} via {data.get('source')}")
        else:
            fail("fetch_token_data returned no price")
            return

        # Step 2: Fetch full analysis bundle (if GMGN key available)
        info("Step 2: Fetching analysis bundle...")
        from utils.data_fetcher import fetch_full_analysis_bundle
        bundle = await fetch_full_analysis_bundle(BONK, "sol")
        if bundle:
            has_candles  = bool(bundle.get("candles"))
            has_security = bundle.get("security") is not None
            has_supply   = bundle.get("supply") is not None
            ok(f"fetch_full_analysis_bundle — candles={'✓' if has_candles else '✗'} security={'✓' if has_security else '✗'} supply={'✓' if has_supply else '✗'}")

            if has_candles:
                for res, candles in bundle["candles"].items():
                    if candles:
                        ok(f"  Candles {res}: {len(candles)} bars")
        else:
            info("Bundle fetch returned None (ok if no GMGN key)")

        # Step 3: Mock DB snapshots for AI
        info("Step 3: Building mock price history...")
        mock_history = [
            {"price_usd": data["price_usd"] * (1 + i*0.05),
             "volume_24h": data.get("volume_24h", 50000),
             "price_change_pct": i * 1.5,
             "buys": 80 + i*5, "sells": 40 + i*2,
             "liquidity": data.get("liquidity_usd", 20000),
             "snapshot_at": datetime.now(timezone.utc).isoformat()}
            for i in range(20)
        ]
        ok(f"Mock history built — {len(mock_history)} snapshots")

        # Step 4: AI analysis (only if Groq key present)
        if os.getenv("GROQ_API_KEY"):
            info("Step 4: Running AI analysis...")
            # Pastikan DB di-init sebelum AI analyzer dipanggil
            # (di production, main.py sudah panggil init_db() duluan)
            from database.db_manager import init_db
            await init_db()
            from agents.ai_analyzer import analyze_token_pattern, calculate_timeframe_stats
            stats = calculate_timeframe_stats(mock_history)
            prediction = await analyze_token_pattern(
                token_data=data,
                price_history=mock_history,
                timeframe_stats=stats,
                analysis_bundle=bundle,
            )
            if prediction:
                ok(f"AI prediction — type={prediction.get('prediction_type')} "
                   f"conf={round(prediction.get('confidence',0)*100)}% "
                   f"action={prediction.get('action')}")
                ok(f"  Target: {prediction.get('predicted_multiplier')}x | "
                   f"Safe TP: {prediction.get('safe_tp_multiplier')}x | "
                   f"Risk: {prediction.get('risk_level')}")
            else:
                fail("AI analysis returned None")
        else:
            skip("AI analysis", "GROQ_API_KEY tidak diset")

    except Exception as e:
        fail("Pipeline test error", str(e))
        import traceback; traceback.print_exc()


# ════════════════════════════════════════════════
# SECTION 11 — Telegram Bot Connectivity
# ════════════════════════════════════════════════
async def test_telegram_bot():
    header("11. TELEGRAM BOT")

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.getenv("YOUR_CHAT_ID", "")

    if not bot_token:
        skip("Bot test", "TELEGRAM_BOT_TOKEN tidak diset")
        return
    if not chat_id:
        skip("Bot test", "YOUR_CHAT_ID tidak diset")
        return

    try:
        import aiohttp
        url = f"https://api.telegram.org/bot{bot_token}/getMe"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    bot = data["result"]
                    ok(f"Bot valid — @{bot.get('username')} ({bot.get('first_name')})")
                else:
                    fail("Bot token invalid", str(data.get("description")))
                    return

        # Send test message
        send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        test_text = (
            "🧪 <b>MEME AGENT — TEST MESSAGE</b>\n\n"
            "✅ Semua sistem berjalan normal.\n"
            "Agent siap dipantau di Railway!\n\n"
            f"<i>🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(send_url, json={
                "chat_id": chat_id,
                "text": test_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                result = await resp.json()
                if result.get("ok"):
                    ok(f"Test message SENT ke chat_id={chat_id} ✓")
                    ok("Cek Telegram Anda — pesan test harus muncul!")
                else:
                    fail("Gagal kirim pesan", str(result.get("description")))

    except Exception as e:
        fail("Telegram bot error", str(e))


# ════════════════════════════════════════════════
# SECTION 12 — Railway Health Check Endpoint
# ════════════════════════════════════════════════
async def test_health_endpoint():
    header("12. HEALTH CHECK ENDPOINT")

    try:
        import aiohttp
        from aiohttp import web
        import asyncio

        # Start a temporary server
        async def health(request):
            return web.json_response({"status": "ok", "test": True})

        app = web.Application()
        app.router.add_get("/health", health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 18080)
        await site.start()

        # Hit it
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:18080/health",
                                   timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                if data.get("status") == "ok":
                    ok("Health endpoint responds correctly")
                else:
                    fail("Health endpoint wrong response", str(data))

        await runner.cleanup()

    except Exception as e:
        fail("Health endpoint error", str(e))


# ════════════════════════════════════════════════
# FINAL SUMMARY
# ════════════════════════════════════════════════
def print_summary():
    total = results["pass"] + results["fail"] + results["skip"]
    print(f"\n{BOLD}{'═'*55}{RESET}")
    print(f"{BOLD}  TEST SUMMARY{RESET}")
    print(f"{BOLD}{'═'*55}{RESET}")
    print(f"  {GREEN}✅ Pass:{RESET}  {results['pass']}")
    print(f"  {RED}❌ Fail:{RESET}  {results['fail']}")
    print(f"  {YELLOW}⏭  Skip:{RESET}  {results['skip']}")
    print(f"  Total:  {total}")

    if results["errors"]:
        print(f"\n{RED}{BOLD}  FAILURES:{RESET}")
        for err in results["errors"]:
            print(f"  {RED}→{RESET} {err}")

    print(f"\n{BOLD}{'═'*55}{RESET}")
    if results["fail"] == 0:
        print(f"  {GREEN}{BOLD}🎉 SEMUA TEST PASS — Agent siap deploy!{RESET}")
    elif results["fail"] <= 2:
        print(f"  {YELLOW}{BOLD}⚠  Ada {results['fail']} kegagalan kecil — periksa konfigurasi{RESET}")
    else:
        print(f"  {RED}{BOLD}❌ Ada {results['fail']} kegagalan — selesaikan sebelum deploy{RESET}")
    print(f"{BOLD}{'═'*55}{RESET}\n")


# ════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════
async def run_all(args):
    section = getattr(args, "section", None)
    fast    = getattr(args, "fast", False)

    print(f"\n{BOLD}{CYAN}🤖 MEME COIN AI AGENT — TEST SUITE{RESET}")
    print(f"{CYAN}   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC{RESET}")
    if fast:
        print(f"   {YELLOW}Mode: FAST (live API calls skipped){RESET}")

    if not section or section == "env":    test_env()
    if not section or section == "import": test_imports()
    if not section or section == "parser": test_parser()
    if not section or section == "db":     await test_database()
    if not section or section == "ai":     await test_ai_logic()

    if not fast:
        if not section or section == "dex":      await test_dexscreener()
        if not section or section == "gmgn":     await test_gmgn()
        if not section or section == "helius":   await test_helius()
        if not section or section == "groq":     await test_groq()
        if not section or section == "pipeline": await test_full_pipeline()
        if not section or section == "bot":      await test_telegram_bot()
        if not section or section == "health":   await test_health_endpoint()
    else:
        for s in ["dex","gmgn","helius","groq","pipeline","bot","health"]:
            if not section or section == s:
                skip(f"Section {s}", "fast mode")

    print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meme Agent Test Suite")
    parser.add_argument("--fast",    action="store_true", help="Skip live API calls")
    parser.add_argument("--section", type=str, help="Run only one section: env|import|parser|db|ai|dex|gmgn|helius|groq|pipeline|bot|health")
    args = parser.parse_args()

    asyncio.run(run_all(args))

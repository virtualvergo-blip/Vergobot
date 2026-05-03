"""
database/db_manager.py
Manages all SQLite operations for the Meme Coin Agent
"""
import aiosqlite
import json
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

DB_PATH = os.getenv("DB_PATH", "data/memeagent.db")

async def init_db():
    """Initialize database and create all tables"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT UNIQUE NOT NULL,
                symbol TEXT,
                name TEXT,
                chain TEXT,
                first_seen_at TEXT NOT NULL,
                call_source TEXT,
                call_message TEXT,
                status TEXT DEFAULT 'monitoring',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                price_usd REAL,
                market_cap REAL,
                volume_24h REAL,
                price_change_pct REAL,
                liquidity REAL,
                buys INTEGER,
                sells INTEGER,
                timeframe TEXT,
                snapshot_at TEXT NOT NULL,
                FOREIGN KEY (contract_address) REFERENCES tokens(contract_address)
            );

            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                pattern_type TEXT NOT NULL,
                pattern_data TEXT NOT NULL,
                timeframe TEXT,
                max_gain_pct REAL,
                max_dump_pct REAL,
                time_to_peak_minutes INTEGER,
                rug_detected INTEGER DEFAULT 0,
                outcome TEXT,
                recorded_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (contract_address) REFERENCES tokens(contract_address)
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                prediction_type TEXT,
                predicted_multiplier REAL,
                safe_tp_multiplier REAL,
                confidence REAL,
                reasoning TEXT,
                ai_raw_response TEXT,
                predicted_at TEXT DEFAULT (datetime('now')),
                resolved_at TEXT,
                actual_multiplier REAL,
                was_correct INTEGER,
                FOREIGN KEY (contract_address) REFERENCES tokens(contract_address)
            );

            CREATE TABLE IF NOT EXISTS agent_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stat_key TEXT UNIQUE NOT NULL,
                stat_value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_price_contract ON price_snapshots(contract_address);
            CREATE INDEX IF NOT EXISTS idx_patterns_contract ON patterns(contract_address);
            CREATE INDEX IF NOT EXISTS idx_predictions_contract ON predictions(contract_address);
        """)
        await db.commit()
    print(f"[DB] Initialized at {DB_PATH}")


async def upsert_token(contract_address: str, symbol: str = None, name: str = None,
                       chain: str = None, call_source: str = None, call_message: str = None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        existing = await db.execute(
            "SELECT id FROM tokens WHERE contract_address = ?", (contract_address,)
        )
        row = await existing.fetchone()
        if row:
            return False  # Already exists
        
        await db.execute("""
            INSERT INTO tokens (contract_address, symbol, name, chain, first_seen_at, call_source, call_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (contract_address, symbol, name, chain, datetime.now(timezone.utc).isoformat(), call_source, call_message))
        await db.commit()
        return True


async def save_price_snapshot(contract_address: str, price_usd: float, market_cap: float,
                               volume_24h: float, price_change_pct: float, liquidity: float,
                               buys: int, sells: int, timeframe: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO price_snapshots 
            (contract_address, price_usd, market_cap, volume_24h, price_change_pct, 
             liquidity, buys, sells, timeframe, snapshot_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (contract_address, price_usd, market_cap, volume_24h, price_change_pct,
              liquidity, buys, sells, timeframe, datetime.now(timezone.utc).isoformat()))
        await db.commit()


async def save_pattern(contract_address: str, pattern_type: str, pattern_data: dict,
                       timeframe: str, max_gain_pct: float, max_dump_pct: float,
                       time_to_peak_minutes: int, rug_detected: bool, outcome: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO patterns 
            (contract_address, pattern_type, pattern_data, timeframe, max_gain_pct,
             max_dump_pct, time_to_peak_minutes, rug_detected, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (contract_address, pattern_type, json.dumps(pattern_data), timeframe,
              max_gain_pct, max_dump_pct, time_to_peak_minutes, int(rug_detected), outcome))
        await db.commit()


async def save_prediction(contract_address: str, prediction_type: str, predicted_multiplier: float,
                          safe_tp_multiplier: float, confidence: float, reasoning: str, ai_raw: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO predictions 
            (contract_address, prediction_type, predicted_multiplier, safe_tp_multiplier,
             confidence, reasoning, ai_raw_response)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (contract_address, prediction_type, predicted_multiplier, safe_tp_multiplier,
              confidence, reasoning, ai_raw))
        await db.commit()


async def get_price_history(contract_address: str, limit: int = 200) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM price_snapshots 
            WHERE contract_address = ? 
            ORDER BY snapshot_at DESC LIMIT ?
        """, (contract_address, limit))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_historical_patterns(limit: int = 500) -> List[Dict]:
    """Get all historical patterns for AI training context"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT p.*, t.symbol, t.chain 
            FROM patterns p
            JOIN tokens t ON p.contract_address = t.contract_address
            ORDER BY p.recorded_at DESC LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_prediction_outcome(contract_address: str, actual_multiplier: float):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, predicted_multiplier FROM predictions 
            WHERE contract_address = ? AND resolved_at IS NULL
            ORDER BY predicted_at DESC LIMIT 1
        """, (contract_address,))
        pred = await cursor.fetchone()
        if pred:
            pred_id, predicted_mult = pred
            was_correct = 1 if actual_multiplier >= (predicted_mult * 0.7) else 0
            await db.execute("""
                UPDATE predictions SET resolved_at = ?, actual_multiplier = ?, was_correct = ?
                WHERE id = ?
            """, (datetime.now(timezone.utc).isoformat(), actual_multiplier, was_correct, pred_id))
            await db.commit()


async def get_winrate_stats() -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        # Total tokens scanned
        cursor = await db.execute("SELECT COUNT(*) FROM tokens")
        total_tokens = (await cursor.fetchone())[0]

        # Predictions stats
        cursor = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(was_correct) as correct,
                AVG(confidence) as avg_confidence
            FROM predictions WHERE resolved_at IS NOT NULL
        """)
        pred_row = await cursor.fetchone()
        total_preds, correct_preds, avg_conf = pred_row

        # Pattern outcomes
        cursor = await db.execute("""
            SELECT outcome, COUNT(*) as cnt FROM patterns GROUP BY outcome
        """)
        outcomes = {row[0]: row[1] for row in await cursor.fetchall()}

        winrate = (correct_preds / total_preds * 100) if total_preds and total_preds > 0 else 0

        return {
            "total_tokens": total_tokens,
            "total_predictions": total_preds or 0,
            "correct_predictions": correct_preds or 0,
            "winrate_pct": round(winrate, 1),
            "avg_confidence": round((avg_conf or 0) * 100, 1),
            "pattern_outcomes": outcomes
        }


async def update_stat(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO agent_stats (stat_key, stat_value) VALUES (?, ?)
            ON CONFLICT(stat_key) DO UPDATE SET stat_value = ?, updated_at = datetime('now')
        """, (key, value, value))
        await db.commit()


async def get_recent_tokens(limit: int = 10) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT t.*, 
                   (SELECT prediction_type FROM predictions WHERE contract_address = t.contract_address ORDER BY predicted_at DESC LIMIT 1) as last_prediction,
                   (SELECT confidence FROM predictions WHERE contract_address = t.contract_address ORDER BY predicted_at DESC LIMIT 1) as last_confidence
            FROM tokens t ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

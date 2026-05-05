"""
utils/message_parser.py

Mengklasifikasikan pesan dari channel signal meme coin.
FIXED v2: Call vs Update detection yang akurat, bonding messages diabaikan.
"""

import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

class MessageType(Enum):
    SIGNAL_CALL = "SIGNAL_CALL"
    UPDATE = "UPDATE"
    PROMO = "PROMO"
    UNKNOWN = "UNKNOWN"

@dataclass
class ParsedSignalCall:
    """Data yang diekstrak dari pesan Signal Call."""
    contract_address: str
    token_name: Optional[str] = None
    token_symbol: Optional[str] = None
    market_cap: Optional[float] = None
    age_minutes: Optional[int] = None
    volume: Optional[float] = None
    liquidity: Optional[float] = None
    dev_sold: Optional[bool] = None
    dex_paid: Optional[bool] = None
    total_holders: Optional[int] = None
    top10_pct: Optional[float] = None
    sniper_count: Optional[int] = None
    bundle_count: Optional[int] = None
    bundle_pct: Optional[float] = None
    gmgn_url: Optional[str] = None
    raw_text: str = ""

@dataclass
class ParsedUpdate:
    """Data yang diekstrak dari pesan Update."""
    token_name: Optional[str] = None
    token_symbol: Optional[str] = None
    contract_address: Optional[str] = None
    multiplier: Optional[float] = None
    premium_multiplier: Optional[float] = None
    mc_from: Optional[float] = None
    mc_to: Optional[float] = None
    within_minutes: Optional[int] = None
    raw_text: str = ""

# ─────────────────────────────────────────────
# Regex Patterns
# ─────────────────────────────────────────────

# Solana contract address (base58, 32-44 chars)
SOL_ADDRESS_RE = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')

# EVM address
EVM_ADDRESS_RE = re.compile(r'\b0x[a-fA-F0-9]{40}\b')

# Token name + symbol: "💊 Kards Kollektors (KARDS)" or "Name (SYM)"
NAME_SYMBOL_RE = re.compile(r'(.+?)\s+\(([A-Za-z0-9]{2,15})\)')

# Multiplier: "6.2x", "10x", "1.5x"
MULTIPLIER_RE = re.compile(r'(\d+(?:\.\d+)?)x', re.IGNORECASE)

# MC value: "30.5K", "193.6K", "1.2M"
MC_VALUE_RE = re.compile(r'(\d+(?:\.\d+)?)\s*([KMB])', re.IGNORECASE)

# Age: "Age: 2h:3m" or "Age: 4m"
AGE_RE = re.compile(r'age[:\s]+(\d+)h?:(\d+)m', re.IGNORECASE)
AGE_SIMPLE_RE = re.compile(r'age[:\s]+(\d+)\s*m', re.IGNORECASE)

# Holders: "TH: 117"
HOLDERS_RE = re.compile(r'\bTH[:\s]+(\d+)', re.IGNORECASE)

# Top 10 %: "Top 10: 17%"
TOP10_RE = re.compile(r'top\s*10[:\s]+(\d+(?:\.\d+)?)\s*%', re.IGNORECASE)

# Sniper: "Sniper: 3"
SNIPER_RE = re.compile(r'sniper[:\s]+(\d+)', re.IGNORECASE)

# Bundle: "Bundle: 0" or "Bundle: 2 buy 10.5%"
BUNDLE_RE = re.compile(r'bundle[:\s]+(\d+)\s*buy\s*(\d+(?:\.\d+)?)\s*%', re.IGNORECASE)
BUNDLE_SIMPLE_RE = re.compile(r'bundle[:\s]+(\d+)', re.IGNORECASE)

# GMGN URL
GMGN_URL_RE = re.compile(r'https?://gmgn\.ai/\S+', re.IGNORECASE)

# Dev sold/hold
DEV_SOLD_RE = re.compile(r'dev[:\s]+.*sold', re.IGNORECASE)
DEV_HOLD_RE = re.compile(r'dev[:\s]+.*hold', re.IGNORECASE)

# Dex paid
DEX_PAID_RE = re.compile(r'dex\s*paid[:\s]*(✅|❌|yes|no)', re.IGNORECASE)

# Within N minutes/days
WITHIN_RE = re.compile(r'within\s+(\d+)\s*(m|min|minutes?|h|hours?|d|days?)', re.IGNORECASE)

# ─────────────────────────────────────────────
# CALL vs UPDATE Detection Helpers
# ─────────────────────────────────────────────

def _has_contract_address(text: str) -> bool:
    """Cek apakah ada contract address yang valid."""
    if EVM_ADDRESS_RE.search(text):
        return True
    for match in SOL_ADDRESS_RE.finditer(text):
        addr = match.group()
        if len(addr) >= 32 and not addr.startswith("http"):
            return True
    return False

def _is_bonding_message(text: str, lower: str) -> bool:
    """Deteksi pesan bonding — ini bukan call baru, bukan update harga."""
    if re.search(r'has\s*been\s*bonded', lower):
        return True
    if re.search(r'bonded\s*,\s*achieved', lower):
        return True
    return False

def _is_promo(text: str, lower: str) -> bool:
    """Deteksi iklan/promosi/recap/ads/bonding."""
    # Bonding messages
    if _is_bonding_message(text, lower):
        return True

    # Ads / promo patterns
    promo_patterns = [
        r'\brenew\s+\d+\s*month',           # "Renew 3 month"
        r'\brecap\s+news',                      # "Recap News"
        r'\bperformance\s+overview',            # "Performance Overview"
        r'\btotal\s+calls:\s*\d+',            # "Total Calls: 2769"
        r'\bwin\s*rate:\s*\d+',               # "Win Rate: 37%"
        r'access\s+vip\s+here',                 # "Access VIP here"
        r't\.me/\+',                              # invite link
        r'advertise\s+across',                    # "Advertise across"
        r'\btake\s+your\s*time',                # "Take your time"
        r'\bended\s+at\s+\d+:\d+\s*utc',     # "ended at 12:00 UTC"
        r'🟪\s*dip\s+mode',                      # "DIP MODE"
        r'🔎\s*call',                             # "Call" badge
        r'🆖\s*advertise',                        # "Advertise"
        r'\bjoin\b.*\bpremium\b.*\bchannel',   # "join premium channel"
        r'\bsubscribe\b.*\bchannel',             # "subscribe channel"
        r'\bvip\b.*\bmembership',               # "vip membership"
        r'\bsignal\b.*\bfree',                  # "signal free"
        r'\bclick\s+here',                       # "click here"
        r'\bfollow\s+us',                        # "follow us"
        r'\bpaid\s+group',                       # "paid group"
        r'\bwhitelist',                           # "whitelist"
    ]
    for pattern in promo_patterns:
        if re.search(pattern, lower):
            return True
    return False

def _is_explicit_update(text: str, lower: str) -> bool:
    """
    Deteksi pesan update yang EXPLICIT.
    Update message = notifikasi hasil/harga setelah call.
    """
    # 1. Format: "🚀$SYMBOL 10.9x(17.9x from PREMIUM)" — signature update
    if re.search(r'\$[A-Za-z0-9]+\s+\d+(?:\.\d+)?x\s*\(\d+(?:\.\d+)?x\s*from\s*premium\)', text, re.IGNORECASE):
        return True

    # 2. "From XK ➡ YK within Z" pattern — signature update
    if re.search(r'from\s+\d+(?:\.\d+)?\s*[kmb]?\s*(?:➡|→|->|▶|↗|⬆)\s*\d+(?:\.\d+)?\s*[kmb]?\s+within', lower):
        return True

    # 3. "Update:" prefix + ada multiplier/gain info (bukan bonding)
    if re.search(r'^\s*update\s*:', lower, re.MULTILINE):
        # Pastikan ini bukan bonding message
        if not _is_bonding_message(text, lower):
            # Cek apakah ada info gain/multiplier/MC change
            if (MULTIPLIER_RE.search(text) or 
                re.search(r'from\s+\d+[\.,]?\d*[kmb]?\s*(?:➡|→|->|▶|↗)', lower) or
                re.search(r'within\s+\d+', lower)):
                return True

    return False

def _is_call_message(text: str, lower: str) -> bool:
    """
    Deteksi pesan call baru.
    Call message = signal awal untuk token baru dengan data lengkap.
    """
    # 1. Ada MC: field (market cap) — hampir selalu ada di call
    if re.search(r'mc[:\s]+\d+(?:\.\d+)?', lower):
        return True

    # 2. Ada Age: field
    if re.search(r'age[:\s]+\d+', lower):
        return True

    # 3. Ada Dev: field (sold/hold)
    if re.search(r'dev[:\s]+', lower):
        return True

    # 4. Ada Dex Paid: field
    if re.search(r'dex\s*paid[:\s]+', lower):
        return True

    # 5. Ada TH: (total holders) field
    if re.search(r'\bth[:\s]+\d+', lower):
        return True

    # 6. Ada Sniper: field
    if re.search(r'sniper[:\s]+\d+', lower):
        return True

    # 7. Ada Bundle: field
    if re.search(r'bundle[:\s]+', lower):
        return True

    # 8. Ada "Chart:" atau "Chart: https://gmgn.ai"
    if re.search(r'chart[:\s]+https?://', lower):
        return True

    # 9. Format emoji + Name (SYM) di awal, diikuti CA di line berikutnya
    lines = text.strip().split("\n")
    if len(lines) >= 2:
        first_line = lines[0].strip()
        second_line = lines[1].strip()
        if NAME_SYMBOL_RE.search(first_line) and _has_contract_address(second_line):
            return True

    return False

# ─────────────────────────────────────────────
# Main Classifier
# ─────────────────────────────────────────────

def classify_message(text: str) -> MessageType:
    """
    Klasifikasikan pesan dengan prioritas:
    1. PROMO — iklan/recap/ads/bonding (diabaikan)
    2. UPDATE — update harga/gain (log outcome)
    3. SIGNAL_CALL — call baru dengan CA (monitor & AI analyze)
    """
    if not text or len(text.strip()) < 10:
        return MessageType.UNKNOWN

    lower = text.lower()

    # ── 1. Cek PROMO dulu (paling mudah dideteksi, diabaikan) ──
    if _is_promo(text, lower):
        return MessageType.PROMO

    # ── 2. Cek UPDATE (explicit update, bukan call) ──
    if _is_explicit_update(text, lower):
        return MessageType.UPDATE

    # ── 3. Cek SIGNAL CALL ──
    # Call message HARUS punya contract address DAN struktur call
    if _has_contract_address(text) and _is_call_message(text, lower):
        return MessageType.SIGNAL_CALL

    # ── 4. Fallback: jika ada CA tapi tidak match call structure ──
    if _has_contract_address(text):
        # Coba cek apakah ini update yang kebetulan ada CA
        if _is_explicit_update(text, lower):
            return MessageType.UPDATE

    return MessageType.UNKNOWN

# ─────────────────────────────────────────────
# Extractor: Signal Call
# ─────────────────────────────────────────────

def extract_signal_call(text: str) -> Optional[ParsedSignalCall]:
    """
    Ekstrak semua data dari pesan Signal Call.
    Mengembalikan None kalau tidak ada contract address.
    """
    # Extract contract address
    contract = None
    evm = EVM_ADDRESS_RE.search(text)
    if evm:
        contract = evm.group()
    else:
        for match in SOL_ADDRESS_RE.finditer(text):
            addr = match.group()
            if len(addr) >= 32 and "http" not in addr:
                contract = addr
                break

    if not contract:
        return None

    result = ParsedSignalCall(contract_address=contract, raw_text=text)

    # Token name + symbol
    name_match = NAME_SYMBOL_RE.search(text)
    if name_match:
        raw_name = name_match.group(1).strip()
        # Hapus emoji dan karakter khusus di awal nama
        raw_name = re.sub(r'^[^\w]+', '', raw_name, flags=re.UNICODE).strip()
        result.token_name = raw_name
        result.token_symbol = name_match.group(2).upper()

    # Market cap: "MC: 30.5K"
    mc_match = re.search(r'mc[:\s]+(\d+(?:\.\d+)?)\s*([KMB])', text, re.IGNORECASE)
    if mc_match:
        result.market_cap = _parse_value(mc_match.group(1), mc_match.group(2))

    # Age: "Age: 2h:3m" atau "Age: 4m"
    age_match = AGE_RE.search(text)
    if age_match:
        hours = int(age_match.group(1) or 0)
        minutes = int(age_match.group(2))
        result.age_minutes = hours * 60 + minutes
    else:
        age_simple = AGE_SIMPLE_RE.search(text)
        if age_simple:
            result.age_minutes = int(age_simple.group(1))

    # Volume: "Volume: 39.0K"
    vol_match = re.search(r'volume[:\s]+(\d+(?:\.\d+)?)\s*([KMB])', text, re.IGNORECASE)
    if vol_match:
        result.volume = _parse_value(vol_match.group(1), vol_match.group(2))

    # Liquidity: "Liquidity: None" atau "Liquidity: 10K"
    liq_match = re.search(r'liquidity[:\s]+(\d+(?:\.\d+)?)\s*([KMB])?', text, re.IGNORECASE)
    if liq_match:
        val = liq_match.group(1)
        unit = liq_match.group(2) or ""
        if unit:
            result.liquidity = _parse_value(val, unit)
        else:
            try:
                result.liquidity = float(val)
            except ValueError:
                pass

    # Dev sold/hold
    if DEV_SOLD_RE.search(text):
        result.dev_sold = True
    elif DEV_HOLD_RE.search(text):
        result.dev_sold = False

    # Dex paid
    dex_match = DEX_PAID_RE.search(text)
    if dex_match:
        val = dex_match.group(1).lower()
        result.dex_paid = val in ("✅", "yes")

    # Total holders
    holders_match = HOLDERS_RE.search(text)
    if holders_match:
        result.total_holders = int(holders_match.group(1))

    # Top 10 %
    top10_match = TOP10_RE.search(text)
    if top10_match:
        result.top10_pct = float(top10_match.group(1))

    # Sniper
    sniper_match = SNIPER_RE.search(text)
    if sniper_match:
        result.sniper_count = int(sniper_match.group(1))

    # Bundle
    bundle_match = BUNDLE_RE.search(text)
    if bundle_match:
        result.bundle_count = int(bundle_match.group(1))
        result.bundle_pct = float(bundle_match.group(2))
    else:
        bundle_simple = BUNDLE_SIMPLE_RE.search(text)
        if bundle_simple:
            result.bundle_count = int(bundle_simple.group(1))

    # GMGN chart URL
    gmgn_match = GMGN_URL_RE.search(text)
    if gmgn_match:
        result.gmgn_url = gmgn_match.group()

    return result

# ─────────────────────────────────────────────
# Extractor: Update
# ─────────────────────────────────────────────

def extract_update(text: str) -> ParsedUpdate:
    """Ekstrak data dari pesan Update."""
    result = ParsedUpdate(raw_text=text)

    # Token name dari "Update: Name (SYM)"
    update_line = re.search(r'update[:\s]+(.+?)(?:\n|$)', text, re.IGNORECASE)
    if update_line:
        line_text = update_line.group(1).strip()
        name_match = NAME_SYMBOL_RE.search(line_text)
        if name_match:
            result.token_name = name_match.group(1).strip()
            result.token_symbol = name_match.group(2).upper()
        else:
            result.token_name = line_text

    # "$SYMBOL" pattern
    if not result.token_symbol:
        dollar_sym = re.search(r'\$([A-Za-z0-9]{2,15})\b', text)
        if dollar_sym:
            result.token_symbol = dollar_sym.group(1).upper()

    # Multiplier: "10.9x(17.9x from PREMIUM)"
    mult_full = re.search(
        r'(\d+(?:\.\d+)?)x\s*\((\d+(?:\.\d+)?)x\s*from\s*premium\)',
        text, re.IGNORECASE
    )
    if mult_full:
        result.multiplier = float(mult_full.group(1))
        result.premium_multiplier = float(mult_full.group(2))
    else:
        mult_match = MULTIPLIER_RE.search(text)
        if mult_match:
            result.multiplier = float(mult_match.group(1))

    # MC from → to: "From 30.0K ↗️ 326.8K"
    mc_range = re.search(
        r'from\s+(\d+(?:\.\d+)?)\s*([KMB]?)\s*(?:➡|→|->|▶|↗|⬆)\s*(\d+(?:\.\d+)?)\s*([KMB]?)',
        text, re.IGNORECASE
    )
    if mc_range:
        result.mc_from = _parse_value(mc_range.group(1), mc_range.group(2))
        result.mc_to = _parse_value(mc_range.group(3), mc_range.group(4))

    # Within N minutes/hours/days
    within_match = WITHIN_RE.search(text)
    if within_match:
        val = int(within_match.group(1))
        unit = within_match.group(2).lower()
        if unit.startswith('d'):
            result.within_minutes = val * 1440
        elif unit.startswith('h'):
            result.within_minutes = val * 60
        else:
            result.within_minutes = val

    # Contract address (kadang ada di footer update)
    evm = EVM_ADDRESS_RE.search(text)
    if evm:
        result.contract_address = evm.group()
    else:
        for match in SOL_ADDRESS_RE.finditer(text):
            addr = match.group()
            if len(addr) >= 32 and "http" not in addr:
                result.contract_address = addr
                break

    return result

# ─────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────

def _parse_value(number: str, unit: str) -> float:
    """Convert '30.5K' → 30500, '1.2M' → 1200000."""
    try:
        n = float(number)
        u = unit.upper() if unit else ""
        if u == "K": return n * 1_000
        if u == "M": return n * 1_000_000
        if u == "B": return n * 1_000_000_000
        return n
    except (ValueError, TypeError):
        return 0.0

def extract_all_addresses(text: str) -> List[str]:
    """Extract semua contract address dari teks."""
    addresses = []
    for m in EVM_ADDRESS_RE.finditer(text):
        addresses.append(m.group())
    for m in SOL_ADDRESS_RE.finditer(text):
        addr = m.group()
        if len(addr) >= 32 and addr not in addresses:
            addresses.append(addr)
    return list(dict.fromkeys(addresses))

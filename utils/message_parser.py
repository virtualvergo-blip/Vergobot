"""
utils/message_parser.py

Mengklasifikasikan pesan dari channel signal meme coin ke 3 tipe:
  1. SIGNAL_CALL   — call token baru dengan contract address
  2. UPDATE        — notifikasi update harga token yang sudah di-call
  3. PROMO         — iklan / promosi / noise, diabaikan

Juga mengekstrak data terstruktur dari setiap tipe.
"""

import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum


class MessageType(Enum):
    SIGNAL_CALL = "SIGNAL_CALL"
    UPDATE      = "UPDATE"
    PROMO       = "PROMO"
    UNKNOWN     = "UNKNOWN"


@dataclass
class ParsedSignalCall:
    """Data yang diekstrak dari pesan Signal Call."""
    contract_address: str
    token_name:       Optional[str]   = None
    token_symbol:     Optional[str]   = None
    market_cap:       Optional[float] = None   # dalam USD
    age_minutes:      Optional[int]   = None
    volume:           Optional[float] = None
    liquidity:        Optional[float] = None
    dev_sold:         Optional[bool]  = None
    dex_paid:         Optional[bool]  = None
    total_holders:    Optional[int]   = None
    top10_pct:        Optional[float] = None
    sniper_count:     Optional[int]   = None
    bundle_count:     Optional[int]   = None
    bundle_pct:       Optional[float] = None
    gmgn_url:         Optional[str]   = None
    raw_text:         str             = ""


@dataclass
class ParsedUpdate:
    """Data yang diekstrak dari pesan Update."""
    token_name:        Optional[str]   = None
    token_symbol:      Optional[str]   = None
    contract_address:  Optional[str]   = None
    multiplier:        Optional[float] = None   # e.g. 6.2 dari "6.2x"
    premium_multiplier: Optional[float] = None  # e.g. 9.6 dari "9.6x from PREMIUM"
    mc_from:           Optional[float] = None
    mc_to:             Optional[float] = None
    within_minutes:    Optional[int]   = None
    raw_text:          str             = ""


# ─────────────────────────────────────────────
# Keyword sets
# ─────────────────────────────────────────────

# Update message indicators
UPDATE_KEYWORDS = [
    r"\bupdate\b",
    r"\bfrom premium\b",
    r"\bx from\b",
    r"\bwithin \d+m\b",
    r"🔥.*\$\w+.*\d+(\.\d+)?x",
    r"🚀.*\$\w+.*\d+(\.\d+)?x",
]

# Promo/ad indicators — no contract address, just marketing
# CATATAN: jangan terlalu agresif — channel pumpfunnevadie sering menyebut
# "PREMIUM" dalam konteks update multiplier (bukan iklan)
PROMO_KEYWORDS = [
    r"\bjoin\b.*\bpremium\b.*\bchannel\b",  # harus ada "channel" supaya tidak false positive
    r"\bsubscribe\b.*\bchannel\b",
    r"\bvip\b.*\bmembership\b",
    r"\bsignal\b.*\bfree\b",
    r"\bclick here\b",
    r"\bt\.me/\+",           # invite link
    r"\bfollow us\b",
    r"\bpaid group\b",
    r"\bwhitelist\b",
]

# Solana contract address pattern (base58, 32–44 chars)
SOL_ADDRESS_RE = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')

# EVM address pattern
EVM_ADDRESS_RE = re.compile(r'\b0x[a-fA-F0-9]{40}\b')

# Multiplier pattern: "6.2x" or "10x"
MULTIPLIER_RE  = re.compile(r'(\d+(?:\.\d+)?)x', re.IGNORECASE)

# MC value: "29.5K", "193.6K", "1.2M"
MC_VALUE_RE    = re.compile(r'(\d+(?:\.\d+)?)\s*([KMB])', re.IGNORECASE)

# Within N minutes
WITHIN_RE      = re.compile(r'within\s+(\d+)\s*m', re.IGNORECASE)

# Age pattern: "Age: 4m"
AGE_RE         = re.compile(r'age[:\s]+(\d+)\s*m', re.IGNORECASE)

# Holders: "TH: 174"
HOLDERS_RE     = re.compile(r'\bTH[:\s]+(\d+)', re.IGNORECASE)

# Top 10 %
TOP10_RE       = re.compile(r'top\s*10[:\s]+(\d+(?:\.\d+)?)\s*%', re.IGNORECASE)

# Sniper
SNIPER_RE      = re.compile(r'sniper[:\s]+(\d+)', re.IGNORECASE)

# Bundle: "Bundle: 2 buy 10.5% with 4 SOL"
BUNDLE_RE      = re.compile(r'bundle[:\s]+(\d+)\s*buy\s*(\d+(?:\.\d+)?)\s*%', re.IGNORECASE)

# Token name+symbol: "Mini Me (MINIME)" or "💊 Mini Me (MINIME)"
NAME_SYMBOL_RE = re.compile(r'(?:[\U00010000-\U0010ffff]|\S+)?\s*(.+?)\s+\(([A-Z0-9]{2,12})\)')

# GMGN URL
GMGN_URL_RE    = re.compile(r'https?://gmgn\.ai/\S+', re.IGNORECASE)

# Dev sold
DEV_SOLD_RE    = re.compile(r'dev[:\s]+.*sold', re.IGNORECASE)
DEV_HOLD_RE    = re.compile(r'dev[:\s]+.*hold', re.IGNORECASE)

# Dex paid
DEX_PAID_RE    = re.compile(r'dex paid[:\s]*(✅|❌|yes|no)', re.IGNORECASE)


# ─────────────────────────────────────────────
# Main classifier
# ─────────────────────────────────────────────
def classify_message(text: str) -> MessageType:
    """
    Klasifikasikan pesan ke SIGNAL_CALL, UPDATE, PROMO, atau UNKNOWN.
    """
    if not text or len(text.strip()) < 10:
        return MessageType.UNKNOWN

    lower = text.lower()

    # ── 1. Cek UPDATE dulu (sebelum signal, karena update kadang ada address juga)
    if _is_update(lower, text):
        return MessageType.UPDATE

    # ── 2. Cek PROMO
    if _is_promo(lower) and not _has_contract_address(text):
        return MessageType.PROMO

    # ── 3. Cek SIGNAL CALL — harus ada contract address
    if _has_contract_address(text):
        # Pastikan bukan update yang kebetulan ada address di footer
        if not _is_update(lower, text):
            return MessageType.SIGNAL_CALL

    return MessageType.UNKNOWN


def _is_update(lower: str, text: str) -> bool:
    """Deteksi pesan update berdasarkan keyword dan pola multiplier."""
    # Explicit "Update:" prefix (paling reliable)
    if re.search(r'^\s*update\s*:', lower, re.MULTILINE):
        return True

    # Ada multiplier + "within Nm" pattern
    has_multiplier = bool(MULTIPLIER_RE.search(text))
    has_within     = bool(WITHIN_RE.search(text))
    if has_multiplier and has_within:
        return True

    # "Nx from PREMIUM" pattern
    if re.search(r'\d+(\.\d+)?x.*from\s+premium', lower):
        return True

    # "From 31.1K ➡/→/-> 193.6K" pattern
    if re.search(r'from\s+\d+[\.,]?\d*[kmb]?\s*(?:➡|→|->|▶|↗)', lower):
        return True

    return False


def _is_promo(lower: str) -> bool:
    """Deteksi iklan/promosi."""
    for pattern in PROMO_KEYWORDS:
        if re.search(pattern, lower):
            return True
    return False


def _has_contract_address(text: str) -> bool:
    """Cek apakah ada contract address yang valid."""
    # EVM
    if EVM_ADDRESS_RE.search(text):
        return True
    # Solana — filter false positives (kata pendek, URLs)
    for match in SOL_ADDRESS_RE.finditer(text):
        addr = match.group()
        if len(addr) >= 32 and not addr.startswith("http"):
            return True
    return False


# ─────────────────────────────────────────────
# Extractor: Signal Call
# ─────────────────────────────────────────────
def extract_signal_call(text: str) -> Optional[ParsedSignalCall]:
    """
    Ekstrak semua data dari pesan Signal Call.
    Mengembalikan None kalau tidak ada contract address.
    """
    # ── Extract contract address
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

    # ── Token name + symbol
    name_match = NAME_SYMBOL_RE.search(text)
    if name_match:
        result.token_name   = name_match.group(1).strip()
        result.token_symbol = name_match.group(2).strip()

    # ── Market cap
    mc_match = re.search(r'mc[:\s]+(\d+(?:\.\d+)?)\s*([KMB])', text, re.IGNORECASE)
    if mc_match:
        result.market_cap = _parse_value(mc_match.group(1), mc_match.group(2))

    # ── Age
    age_match = AGE_RE.search(text)
    if age_match:
        result.age_minutes = int(age_match.group(1))

    # ── Volume
    vol_match = re.search(r'volume[:\s]+(\d+(?:\.\d+)?)\s*([KMB])', text, re.IGNORECASE)
    if vol_match:
        result.volume = _parse_value(vol_match.group(1), vol_match.group(2))

    # ── Liquidity
    liq_match = re.search(r'liquidity[:\s]+(\d+(?:\.\d+)?)\s*([KMB])?', text, re.IGNORECASE)
    if liq_match:
        val = liq_match.group(1)
        unit = liq_match.group(2) or ""
        if unit:
            result.liquidity = _parse_value(val, unit)
        elif "none" not in text.lower()[liq_match.start():liq_match.end()+10]:
            try:
                result.liquidity = float(val)
            except ValueError:
                pass

    # ── Dev sold/hold
    if DEV_SOLD_RE.search(text):
        result.dev_sold = True
    elif DEV_HOLD_RE.search(text):
        result.dev_sold = False

    # ── Dex paid
    dex_match = DEX_PAID_RE.search(text)
    if dex_match:
        val = dex_match.group(1).lower()
        result.dex_paid = val in ("✅", "yes")

    # ── Total holders
    holders_match = HOLDERS_RE.search(text)
    if holders_match:
        result.total_holders = int(holders_match.group(1))

    # ── Top 10 %
    top10_match = TOP10_RE.search(text)
    if top10_match:
        result.top10_pct = float(top10_match.group(1))

    # ── Sniper
    sniper_match = SNIPER_RE.search(text)
    if sniper_match:
        result.sniper_count = int(sniper_match.group(1))

    # ── Bundle
    bundle_match = BUNDLE_RE.search(text)
    if bundle_match:
        result.bundle_count = int(bundle_match.group(1))
        result.bundle_pct   = float(bundle_match.group(2))

    # ── GMGN chart URL
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

    # ── Token name + symbol
    # 1. From "Update: TokenName (SYM)" line
    update_line = re.search(r'update[:\s]+(.+?)(?:\n|$)', text, re.IGNORECASE)
    if update_line:
        name_match = NAME_SYMBOL_RE.search(update_line.group(1))
        if name_match:
            result.token_name   = name_match.group(1).strip()
            result.token_symbol = name_match.group(2).strip()
        else:
            result.token_name = update_line.group(1).strip()

    # 2. "$SYMBOL" pattern anywhere in message (e.g. "$BUTT 6.2x...")
    if not result.token_symbol:
        dollar_sym = re.search(r'\$([A-Z]{2,12})\b', text)
        if dollar_sym:
            result.token_symbol = dollar_sym.group(1)

    # ── Multiplier: "6.2x(9.6x from PREMIUM)"
    mult_full = re.search(
        r'(\d+(?:\.\d+)?)x\s*\((\d+(?:\.\d+)?)x\s*from\s*premium\)',
        text, re.IGNORECASE
    )
    if mult_full:
        result.multiplier         = float(mult_full.group(1))
        result.premium_multiplier = float(mult_full.group(2))
    else:
        # Fallback: ambil multiplier pertama saja
        mult_match = MULTIPLIER_RE.search(text)
        if mult_match:
            result.multiplier = float(mult_match.group(1))

    # ── MC from → to: "From 31.1K ➡ 193.6K" or "From 45K -> 382K"
    mc_range = re.search(
        r'from\s+(\d+(?:\.\d+)?)\s*([KMB]?)\s*(?:➡|→|->|▶|↗|⬆)\s*(\d+(?:\.\d+)?)\s*([KMB]?)',
        text, re.IGNORECASE
    )
    if mc_range:
        result.mc_from = _parse_value(mc_range.group(1), mc_range.group(2))
        result.mc_to   = _parse_value(mc_range.group(3), mc_range.group(4))

    # ── Within N minutes
    within_match = WITHIN_RE.search(text)
    if within_match:
        result.within_minutes = int(within_match.group(1))

    # ── Contract address (kadang ada di footer update)
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
    """Convert '29.5K' → 29500, '1.2M' → 1200000."""
    try:
        n = float(number)
        u = unit.upper() if unit else ""
        if u == "K":   return n * 1_000
        if u == "M":   return n * 1_000_000
        if u == "B":   return n * 1_000_000_000
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

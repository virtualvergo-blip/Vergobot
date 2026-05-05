# Vergobot Fixes — Bot Not Responding to Calls

## Problem
Bot successfully connected to Telegram and resolved `@pumpfunnevadie`, but **never detected any SIGNAL_CALL messages**. Log only showed:
```
[Listener] Ready. Listening for calls...
```
With no "New call detected" or processing logs.

## Root Causes Found

### 1. 🚨 CRITICAL: Message Parser Misclassified Calls as Updates
**File:** `utils/message_parser.py`

The `_is_update()` function was too aggressive:
```python
# OLD — WRONG: Any message with "6.2x" was classified as UPDATE
if MULTIPLIER_RE.search(text) and WITHIN_RE.search(text):
    return True  # ← Call messages also contain "1.5x" in PREMIUM notes!
```

Call messages from `@pumpfunnevadie` contain:
- `NOTE: In PREMIUM, the profit will be 1.5x --> 2x before public`
- This triggered the multiplier regex → classified as UPDATE
- Result: **All calls were ignored!**

**Fix:** Complete rewrite of `classify_message()` with explicit detection:
- **PROMO** first (ads, recaps, bonding messages) → ignored
- **UPDATE** only if explicit patterns: `Update:`, `$SYM Nx from PREMIUM`, `From X ➡ Y within Z`, `has been bonded`
- **SIGNAL_CALL** requires: contract address + call structure (MC:, Age:, Dev:, Dex Paid:, TH:, Sniper:, Bundle:, Chart:)

### 2. 🐛 Missing `agents/bot_commands.py`
**File:** `main.py` imports `start_polling` from `agents.bot_commands`, but the file didn't exist.

**Fix:** Created complete `agents/bot_commands.py` with `/status`, `/tokens`, `/active`, `/help` commands.

### 3. 🐛 `fetch_price_only()` Missing `buys_5m`/`sells_5m`
**File:** `utils/data_fetcher.py`

`fetch_price_only()` (used in polling loop) didn't return `buys_5m`/`sells_5m`, so all snapshots saved with 0 buys/sells.

**Fix:** Added `buys_5m` and `sells_5m` to GMGN and DexScreener responses.

### 4. 🐛 `update_prediction_outcome()` Signature Mismatch
**File:** `database/db_manager.py`

`token_monitor.py` called `update_prediction_outcome(pred_id, outcome, final_mult)` (3 args) but function only accepted 2 args.

**Fix:** Split into two functions:
- `update_prediction_outcome(prediction_id, actual_multiplier)` — used by token_monitor
- `update_prediction_outcome_by_address(contract_address, actual_multiplier)` — used by channel_listener for update messages

### 5. 🐛 AI Analysis Only at End of Session
**File:** `agents/token_monitor.py`

AI analysis was only performed at the END of the monitoring session (30-60 min), not when the call first arrived.

**Fix:** Moved initial AI analysis to `channel_listener.py` — immediately analyzes and sends prediction alert when call is detected. End-of-session analysis in `token_monitor.py` continues for pattern learning.

## Files Changed

| File | Action | Key Changes |
|------|--------|-------------|
| `utils/message_parser.py` | **Rewrite** | Explicit call vs update detection, promo filtering |
| `agents/channel_listener.py` | **Fix** | Immediate AI analysis on call, better logging |
| `agents/token_monitor.py` | **Fix** | Proper `update_prediction_outcome` call with pred_id |
| `utils/data_fetcher.py` | **Fix** | `fetch_price_only` returns buys/sells |
| `database/db_manager.py` | **Fix** | Two variants of `update_prediction_outcome` |
| `agents/bot_commands.py` | **New** | Complete bot command handler |

## Message Classification Results

Tested against your uploaded messages:

| Message Type | Result | Action |
|-------------|--------|--------|
| **Call Message** (`💊 Kards Kollektors...`) | ✅ `SIGNAL_CALL` | Monitor + AI analyze |
| **Update Message** (`Update: chimping out...`) | ✅ `UPDATE` | Log outcome |
| **Bonding Message** (`Update: Kards...bonded`) | ✅ `PROMO` | Ignore |
| **Announce Message** (`🟪 DIP MODE...`) | ✅ `PROMO` | Ignore |
| **Recap Message** (`📣 VIP PUMPFUN Recap...`) | ✅ `PROMO` | Ignore |
| **Ads Message** (`Renew 3 month...`) | ✅ `PROMO` | Ignore |

## Deployment Steps

1. Replace the 6 files in your repository
2. Commit and push to GitHub
3. Redeploy to Railway
4. Monitor logs — you should see:
```
[Listener] 📨 [SIGNAL_CALL] from @pumpfunnevadie
[Listener] 🎯 SIGNAL_CALL detected! Processing...
[Listener] 🆕 New call: KARDS (6FHc8u...) chain=sol
[Listener] 🤖 Running initial AI analysis for KARDS...
[Listener] 🧠 AI Prediction: PUMP | Confidence: 0.72
[Listener] ✅ Initial prediction alert sent for KARDS
```

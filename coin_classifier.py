import numpy as np
from datetime import datetime
import database as db
import logging

log = logging.getLogger(__name__)


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if not trs:
        return 0
    return sum(trs[-period:]) / period


def classify_volatility(candles):
    if len(candles) < 30:
        return "orta"
    atr = calculate_atr(candles)
    avg_price = sum(c["close"] for c in candles[-14:]) / 14
    if avg_price == 0:
        return "orta"
    atr_pct = (atr / avg_price) * 100

    if atr_pct < 2:
        return "dusuk"
    elif atr_pct < 5:
        return "orta"
    return "yuksek"


def classify_volume_profile(candles):
    if len(candles) < 30:
        return "orta"
    volumes = [c["quote_volume"] for c in candles[-30:] if c["quote_volume"]]
    if not volumes:
        return "orta"
    avg_vol = sum(volumes) / len(volumes)
    if avg_vol < 1_000_000:
        return "dusuk"
    elif avg_vol < 50_000_000:
        return "orta"
    return "yuksek"


def calculate_btc_correlation(symbol_candles, btc_candles, period=30):
    if len(symbol_candles) < period or len(btc_candles) < period:
        return 0, "orta"

    btc_by_time = {c["open_time"]: c for c in btc_candles}
    sym_returns = []
    btc_returns = []

    sym_slice = symbol_candles[-period:]
    for i in range(1, len(sym_slice)):
        prev_time = sym_slice[i - 1]["open_time"]
        curr_time = sym_slice[i]["open_time"]
        btc_prev = btc_by_time.get(prev_time)
        btc_curr = btc_by_time.get(curr_time)
        if not btc_prev or not btc_curr:
            continue
        if sym_slice[i - 1]["close"] > 0 and btc_prev["close"] > 0:
            sym_ret = (sym_slice[i]["close"] - sym_slice[i - 1]["close"]) / sym_slice[i - 1]["close"]
            btc_ret = (btc_curr["close"] - btc_prev["close"]) / btc_prev["close"]
            sym_returns.append(sym_ret)
            btc_returns.append(btc_ret)

    if len(sym_returns) < 10:
        return 0, "orta"

    sym_arr = np.array(sym_returns)
    btc_arr = np.array(btc_returns)

    sym_std = np.std(sym_arr)
    btc_std = np.std(btc_arr)
    if sym_std == 0 or btc_std == 0:
        return 0, "orta"

    correlation = float(np.corrcoef(sym_arr, btc_arr)[0, 1])

    if abs(correlation) > 0.7:
        group = "yuksek"
    elif abs(correlation) > 0.4:
        group = "orta"
    else:
        group = "dusuk"

    return round(correlation, 3), group


def classify_all_coins():
    log.info("Classifying all coins...")
    coins = db.get_all_coins()
    btc_candles_raw = db.get_candles("BTCUSDT", "1d", 60)
    btc_candles = [dict(c) for c in reversed(btc_candles_raw)]

    conn = db.get_conn()
    classified = 0
    now = datetime.utcnow().isoformat()
    for coin in coins:
        symbol = coin["symbol"]
        if symbol == "BTCUSDT":
            continue

        try:
            candles_raw = db.get_candles(symbol, "1d", 60)
            if not candles_raw:
                continue
            candles = [dict(c) for c in reversed(candles_raw)]

            vol_class = classify_volatility(candles)
            vol_profile = classify_volume_profile(candles)
            corr, corr_group = calculate_btc_correlation(candles, btc_candles)

            avg_vol = 0
            volumes = [c["quote_volume"] for c in candles[-30:] if c["quote_volume"]]
            if volumes:
                avg_vol = sum(volumes) / len(volumes)

            conn.execute(
                "UPDATE coins SET volatility_class=?, volume_profile=?, btc_correlation=?, "
                "btc_correlation_group=?, avg_daily_volume=?, last_classified=? WHERE symbol=?",
                (vol_class, vol_profile, corr, corr_group, avg_vol, now, symbol)
            )
            classified += 1
        except Exception as e:
            log.error(f"Classify error for {symbol}: {e}")
            continue

    conn.commit()
    log.info(f"Classified {classified} coins")
    return classified

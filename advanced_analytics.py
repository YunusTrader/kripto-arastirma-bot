import logging
import time
import numpy as np
import database as db
from config import SECTORS, TIMEFRAME_MINUTES

log = logging.getLogger(__name__)


# ─── WHALE / BÜYÜK İŞLEM TESPİTİ ─────────────────────────────────
# Mum verisinden: quote_volume / num_trades = ortalama işlem büyüklüğü
# 30 günlük ortalamanın 5x+ üstü → whale birikimi sinyali

WHALE_RATIO_THRESHOLD = 5.0
WHALE_LOOKBACK = 30


def detect_whale_activity(symbol, timeframe="4h"):
    candles_raw = db.get_candles(symbol, timeframe, 200)
    if not candles_raw or len(candles_raw) < WHALE_LOOKBACK + 5:
        return []

    candles = [dict(c) for c in reversed(candles_raw)]
    alerts = []

    for i in range(WHALE_LOOKBACK, len(candles)):
        current = candles[i]
        num_trades = current.get("num_trades", 0)
        if not num_trades or num_trades == 0:
            continue

        current_avg = current["quote_volume"] / num_trades

        lookback = candles[i - WHALE_LOOKBACK:i]
        normal_avgs = []
        for c in lookback:
            nt = c.get("num_trades", 0)
            if nt > 0:
                normal_avgs.append(c["quote_volume"] / nt)

        if not normal_avgs:
            continue

        normal_avg = sum(normal_avgs) / len(normal_avgs)
        if normal_avg == 0:
            continue

        ratio = current_avg / normal_avg
        if ratio >= WHALE_RATIO_THRESHOLD:
            alerts.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "detected_time": current["open_time"],
                "avg_trade_size": round(current_avg, 2),
                "normal_avg_trade_size": round(normal_avg, 2),
                "ratio": round(ratio, 1),
                "price_at_detection": current["close"],
            })

    return alerts


def run_whale_scan(timeframe="4h"):
    log.info("Running whale activity scan...")
    coins = db.get_all_coins()
    conn = db.get_conn()
    total = 0

    for coin in coins:
        symbol = coin["symbol"]
        if symbol == "BTCUSDT":
            continue
        alerts = detect_whale_activity(symbol, timeframe)
        for a in alerts:
            # Check for price after 24h
            tf_minutes = TIMEFRAME_MINUTES.get(timeframe, 240)
            bars_24h = max(1, int(1440 / tf_minutes))
            candles_raw = db.get_candles(symbol, timeframe, 500)
            if candles_raw:
                candles = [dict(c) for c in reversed(candles_raw)]
                for j, c in enumerate(candles):
                    if c["open_time"] == a["detected_time"] and j + bars_24h < len(candles):
                        a["price_after_24h"] = candles[j + bars_24h]["close"]
                        if a["price_at_detection"] > 0:
                            a["pct_change_24h"] = round(
                                (a["price_after_24h"] - a["price_at_detection"]) / a["price_at_detection"] * 100, 2
                            )
                        break

            cols = ", ".join(a.keys())
            placeholders = ", ".join(["?"] * len(a))
            conn.execute(f"INSERT INTO whale_alerts ({cols}) VALUES ({placeholders})", list(a.values()))
            total += 1

    conn.commit()
    log.info(f"Whale scan complete: {total} alerts found")
    return total


# ─── KORELASYON KIRILMA TESPİTİ ──────────────────────────────────
# 30 günlük BTC korelasyonu vs son 2 günlük korelasyon
# Fark >= 0.4 → korelasyon kırılması (coin bağımsız hareket ediyor)

CORR_BREAK_THRESHOLD = 0.4
CORR_SHORT_PERIOD = 2  # gün (48 saat)
CORR_LONG_PERIOD = 30  # gün


def detect_correlation_breaks():
    log.info("Detecting correlation breaks...")
    coins = db.get_all_coins()
    btc_raw = db.get_candles("BTCUSDT", "1d", 60)
    if not btc_raw or len(btc_raw) < CORR_LONG_PERIOD:
        return []

    btc_candles = [dict(c) for c in reversed(btc_raw)]
    btc_returns_30 = []
    for i in range(1, min(CORR_LONG_PERIOD + 1, len(btc_candles))):
        if btc_candles[i - 1]["close"] > 0:
            btc_returns_30.append(
                (btc_candles[i]["close"] - btc_candles[i - 1]["close"]) / btc_candles[i - 1]["close"]
            )

    btc_returns_short = btc_returns_30[-CORR_SHORT_PERIOD:] if len(btc_returns_30) >= CORR_SHORT_PERIOD else []

    results = []
    regime = db.get_latest_regime()
    btc_trend = dict(regime).get("btc_trend", "yatay") if regime else "yatay"

    for coin in coins:
        symbol = coin["symbol"]
        if symbol == "BTCUSDT":
            continue

        raw = db.get_candles(symbol, "1d", 60)
        if not raw or len(raw) < CORR_LONG_PERIOD:
            continue
        candles = [dict(c) for c in reversed(raw)]

        sym_returns_30 = []
        for i in range(1, min(CORR_LONG_PERIOD + 1, len(candles))):
            if candles[i - 1]["close"] > 0:
                sym_returns_30.append(
                    (candles[i]["close"] - candles[i - 1]["close"]) / candles[i - 1]["close"]
                )

        if len(sym_returns_30) < CORR_LONG_PERIOD - 1:
            continue

        sym_returns_short = sym_returns_30[-CORR_SHORT_PERIOD:] if len(sym_returns_30) >= CORR_SHORT_PERIOD else []

        min_len_30 = min(len(sym_returns_30), len(btc_returns_30))
        if min_len_30 < 10:
            continue

        corr_30 = float(np.corrcoef(
            np.array(sym_returns_30[-min_len_30:]),
            np.array(btc_returns_30[-min_len_30:])
        )[0, 1])

        if len(sym_returns_short) >= CORR_SHORT_PERIOD and len(btc_returns_short) >= CORR_SHORT_PERIOD:
            min_len_s = min(len(sym_returns_short), len(btc_returns_short))
            if min_len_s >= 2:
                corr_48 = float(np.corrcoef(
                    np.array(sym_returns_short[-min_len_s:]),
                    np.array(btc_returns_short[-min_len_s:])
                )[0, 1])
            else:
                continue
        else:
            continue

        if np.isnan(corr_30) or np.isnan(corr_48):
            continue

        diff = abs(corr_30 - corr_48)
        if diff >= CORR_BREAK_THRESHOLD and corr_30 > 0.5:
            results.append({
                "symbol": symbol,
                "detected_time": int(time.time()),
                "corr_30d": round(corr_30, 3),
                "corr_48h": round(corr_48, 3),
                "corr_diff": round(diff, 3),
                "price_at_detection": candles[-1]["close"],
                "btc_trend": btc_trend,
                "sector": coin.get("sector", "Diger"),
            })

    conn = db.get_conn()
    for r in results:
        cols = ", ".join(r.keys())
        placeholders = ", ".join(["?"] * len(r))
        conn.execute(f"INSERT INTO correlation_breaks ({cols}) VALUES ({placeholders})", list(r.values()))
    conn.commit()

    log.info(f"Correlation breaks: {len(results)} detected")
    return results


# ─── SEKTÖR LİDER-TAKİPÇİ ANALİZİ ──────────────────────────────
# Her sektörün market cap'e göre ilk coini "lider"
# Lider %5+ hareket ettiğinde, diğerleri kaç saat gecikmeyle takip ediyor?

LEADER_MOVE_THRESHOLD = 5.0  # %
FOLLOWER_WINDOW_HOURS = 48

SECTOR_LEADERS = {
    "L1": "ETHUSDT",
    "L2": "ARBUSDT",
    "DeFi": "UNIUSDT",
    "AI": "FETUSDT",
    "Meme": "DOGEUSDT",
    "Gaming": "AXSUSDT",
    "Altyapi": "LINKUSDT",
}


def analyze_leader_follower(timeframe="4h"):
    log.info("Analyzing sector leader-follower patterns...")
    tf_minutes = TIMEFRAME_MINUTES.get(timeframe, 240)
    follower_bars = int(FOLLOWER_WINDOW_HOURS * 60 / tf_minutes)

    conn = db.get_conn()
    total = 0

    for sector, members in SECTORS.items():
        leader_sym = SECTOR_LEADERS.get(sector)
        if not leader_sym:
            continue

        leader_raw = db.get_candles(leader_sym, timeframe, 500)
        if not leader_raw or len(leader_raw) < 30:
            continue
        leader_candles = [dict(c) for c in reversed(leader_raw)]

        # Find leader moves
        for i in range(1, len(leader_candles)):
            if leader_candles[i - 1]["close"] == 0:
                continue
            move = (leader_candles[i]["close"] - leader_candles[i - 1]["close"]) / leader_candles[i - 1]["close"] * 100

            if abs(move) < LEADER_MOVE_THRESHOLD:
                continue

            move_time = leader_candles[i]["open_time"]

            # Check followers
            for member in members:
                follower_sym = f"{member}USDT"
                if follower_sym == leader_sym:
                    continue

                f_raw = db.get_candles(follower_sym, timeframe, 500)
                if not f_raw:
                    continue
                f_candles = [dict(c) for c in reversed(f_raw)]

                # Find the candle at leader move time
                f_base_idx = None
                for j, fc in enumerate(f_candles):
                    if fc["open_time"] == move_time:
                        f_base_idx = j
                        break

                if f_base_idx is None:
                    continue

                # Look for follower reaction within window
                f_base_price = f_candles[f_base_idx]["close"]
                if f_base_price == 0:
                    continue

                best_follow = None
                for k in range(1, min(follower_bars + 1, len(f_candles) - f_base_idx)):
                    f_price = f_candles[f_base_idx + k]["close"]
                    f_move = (f_price - f_base_price) / f_base_price * 100

                    # Same direction move
                    if (move > 0 and f_move >= LEADER_MOVE_THRESHOLD * 0.5) or \
                       (move < 0 and f_move <= -LEADER_MOVE_THRESHOLD * 0.5):
                        delay_hours = (k * tf_minutes) / 60
                        if best_follow is None or abs(f_move) > abs(best_follow["follower_move_pct"]):
                            best_follow = {
                                "sector": sector,
                                "leader_symbol": leader_sym,
                                "leader_move_pct": round(move, 2),
                                "leader_move_time": move_time,
                                "follower_symbol": follower_sym,
                                "follower_move_pct": round(f_move, 2),
                                "follower_delay_hours": round(delay_hours, 1),
                                "timeframe": timeframe,
                            }

                if best_follow:
                    cols = ", ".join(best_follow.keys())
                    placeholders = ", ".join(["?"] * len(best_follow))
                    conn.execute(f"INSERT INTO sector_leaders ({cols}) VALUES ({placeholders})",
                                 list(best_follow.values()))
                    total += 1

    conn.commit()
    log.info(f"Leader-follower analysis: {total} patterns found")
    return total


def run_all_advanced_analytics():
    log.info("Running all advanced analytics...")
    run_whale_scan("4h")
    detect_correlation_breaks()
    analyze_leader_follower("4h")
    log.info("Advanced analytics complete")

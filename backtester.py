import json
import time
import logging
from datetime import datetime
from config import (
    SCORE_MIN_SAMPLES, TIMEFRAMES, TIMEFRAME_MINUTES
)
import database as db
from indicators import detect_signals, get_indicator_snapshot

log = logging.getLogger(__name__)

ALL_METHODS = [
    "macd", "ema_20_50", "ema_50_200",
    "bb_squeeze", "bb_breakout", "volume_spike",
    "accumulation", "multi_signal", "whale_activity",
    "rsi_divergence", "obv_trend", "stoch_rsi"
]

DIMENSIONS = [
    "btc_trend", "dominance_trend", "mcap_group",
    "sector", "volatility_class", "volume_profile",
    "btc_correlation_group", "fear_greed_label", "overall"
]


PUMP_THRESHOLDS = {"1h": 10, "4h": 15, "1d": 20}
PUMP_LOOKBACK_BARS = {"1h": 6, "4h": 6, "1d": 3}


def find_pumps(candles, timeframe):
    if len(candles) < 30:
        return []
    pumps = []
    threshold = PUMP_THRESHOLDS.get(timeframe, 10)
    lookback_size = PUMP_LOOKBACK_BARS.get(timeframe, 6)
    cooldown = 0

    for i in range(lookback_size + 1, len(candles) - 1):
        if cooldown > 0:
            cooldown -= 1
            continue
        lookback = min(lookback_size, i)
        base_price = min(c["close"] for c in candles[i - lookback:i])
        if base_price == 0:
            continue
        peak_price = candles[i]["high"]
        pct_change = ((peak_price - base_price) / base_price) * 100

        if pct_change >= threshold:
            pumps.append({
                "index": i,
                "pump_time": candles[i]["open_time"],
                "pump_pct": round(pct_change, 2),
                "price_before": base_price,
                "price_peak": peak_price,
            })
            cooldown = lookback_size
    return pumps


INDICATOR_WINDOW = 60
SIGNAL_WINDOW = 24


def analyze_pump_preconditions(candles, pump_index, timeframe):
    if pump_index < INDICATOR_WINDOW:
        return {}
    indicator_candles = candles[pump_index - INDICATOR_WINDOW:pump_index]
    snapshot = get_indicator_snapshot(indicator_candles)

    signal_start = max(0, pump_index - SIGNAL_WINDOW)
    signal_candles = candles[signal_start:pump_index]
    signals = detect_signals(signal_candles) if len(signal_candles) >= 60 else {}

    return {
        "snapshot": snapshot,
        "signals": list(signals.keys()),
        "signal_count": len(signals),
    }


def run_backtest_for_symbol(symbol, coin_info):
    results = []

    for timeframe in TIMEFRAMES:
        candles_raw = db.get_candles(symbol, timeframe, 1000)
        if not candles_raw or len(candles_raw) < 60:
            continue
        candles = [dict(c) for c in reversed(candles_raw)]
        tf_minutes = TIMEFRAME_MINUTES.get(timeframe, 60)

        # Walk through candles detecting signals
        window_size = 60
        for i in range(window_size, len(candles) - 7):
            window = candles[i - window_size:i + 1]
            signals = detect_signals(window)
            if not signals:
                continue

            price_at = candles[i]["close"]
            if price_at == 0:
                continue

            price_1d = None
            price_3d = None
            price_7d = None
            bars_1d = max(1, int(1440 / tf_minutes))
            bars_3d = max(1, int(4320 / tf_minutes))
            bars_7d = max(1, int(10080 / tf_minutes))

            if i + bars_1d < len(candles):
                price_1d = candles[i + bars_1d]["close"]
            if i + bars_3d < len(candles):
                price_3d = candles[i + bars_3d]["close"]
            if i + bars_7d < len(candles):
                price_7d = candles[i + bars_7d]["close"]

            for method_name, sig_data in signals.items():
                if method_name not in ALL_METHODS:
                    continue

                pct_1d = ((price_1d - price_at) / price_at * 100) if price_1d else None
                pct_3d = ((price_3d - price_at) / price_at * 100) if price_3d else None
                pct_7d = ((price_7d - price_at) / price_at * 100) if price_7d else None

                signal = {
                    "symbol": symbol,
                    "method_name": method_name,
                    "timeframe": timeframe,
                    "signal_time": candles[i]["open_time"],
                    "signal_type": sig_data.get("type", ""),
                    "price_at_signal": price_at,
                    "price_after_1d": price_1d,
                    "price_after_3d": price_3d,
                    "price_after_7d": price_7d,
                    "pct_change_1d": round(pct_1d, 2) if pct_1d is not None else None,
                    "pct_change_3d": round(pct_3d, 2) if pct_3d is not None else None,
                    "pct_change_7d": round(pct_7d, 2) if pct_7d is not None else None,
                    "btc_trend": coin_info.get("btc_trend", "yatay"),
                    "dominance_trend": coin_info.get("dominance_trend", "sabit"),
                    "mcap_group": coin_info.get("mcap_group", "200+"),
                    "sector": coin_info.get("sector", "Diger"),
                    "volatility_class": coin_info.get("volatility_class", "orta"),
                    "volume_profile": coin_info.get("volume_profile", "orta"),
                    "btc_correlation_group": coin_info.get("btc_correlation_group", "orta"),
                    "fear_greed_label": coin_info.get("fear_greed_label", "notr"),
                    "is_success_1d": (1 if pct_1d > 0 else 0) if pct_1d is not None else None,
                    "is_success_3d": (1 if pct_3d > 0 else 0) if pct_3d is not None else None,
                    "is_success_7d": (1 if pct_7d > 0 else 0) if pct_7d is not None else None,
                }
                results.append(signal)

        # Find and analyze pumps
        pumps = find_pumps(candles, timeframe)
        for pump in pumps:
            pre = analyze_pump_preconditions(candles, pump["index"], timeframe)
            snap = pre.get("snapshot", {})
            sigs = pre.get("signals", [])
            pump_record = {
                "symbol": symbol,
                "timeframe": timeframe,
                "pump_time": pump["pump_time"],
                "pump_pct": pump["pump_pct"],
                "price_before": pump["price_before"],
                "price_peak": pump["price_peak"],
                "btc_trend": coin_info.get("btc_trend", "yatay"),
                "dominance_trend": coin_info.get("dominance_trend", "sabit"),
                "mcap_group": coin_info.get("mcap_group", "200+"),
                "sector": coin_info.get("sector", "Diger"),
                "pre_rsi": None,
                "pre_macd_signal": snap.get("macd_signal"),
                "pre_ema_cross": snap.get("ema_cross"),
                "pre_bb_squeeze": 1 if snap.get("bb_squeeze") else 0,
                "pre_volume_ratio": snap.get("volume_ratio"),
                "pre_accumulation": 1 if "accumulation" in sigs else 0,
                "indicators_json": json.dumps(pre),
            }
            cols = ", ".join(pump_record.keys())
            placeholders = ", ".join(["?"] * len(pump_record))
            conn = db.get_conn()
            conn.execute(f"INSERT INTO pumps ({cols}) VALUES ({placeholders})", list(pump_record.values()))

    return results


def run_full_backtest():
    log.info("Running full backtest...")
    coins = db.get_all_coins()
    regime = db.get_latest_regime()
    regime_dict = dict(regime) if regime else {}

    conn = db.get_conn()
    total_signals = 0
    batch_count = 0
    for coin in coins:
        if coin["symbol"] == "BTCUSDT":
            continue
        try:
            coin_info = dict(coin)
            coin_info.update(regime_dict)
            signals = run_backtest_for_symbol(coin["symbol"], coin_info)
            for sig in signals:
                cols = ", ".join(sig.keys())
                placeholders = ", ".join(["?"] * len(sig))
                conn.execute(
                    f"INSERT INTO method_signals ({cols}) VALUES ({placeholders})",
                    list(sig.values())
                )
            total_signals += len(signals)
            batch_count += 1
            if batch_count % 50 == 0:
                conn.commit()
                log.info(f"Backtest progress: {batch_count} coins, {total_signals} signals")
                try:
                    calculate_all_scores()
                    log.info(f"Interim scores calculated at {batch_count} coins")
                except Exception as e:
                    log.error(f"Interim score error: {e}")
        except Exception as e:
            log.error(f"Backtest error for {coin['symbol']}: {e}")
            continue

    conn.commit()
    log.info(f"Backtest complete: {total_signals} signals from {batch_count} coins")
    calculate_all_scores()
    try:
        calculate_pump_condition_scores()
    except Exception as e:
        log.error(f"Pump condition score error: {e}")
    return total_signals


CONDITIONS = ["bb_squeeze", "bb_breakout", "volume_spike", "accumulation",
              "macd", "ema_20_50", "ema_50_200", "whale_activity", "multi_signal",
              "rsi_divergence", "obv_trend", "stoch_rsi"]
PUMP_FORWARD_BARS = {"1h": 24, "4h": 6, "1d": 3}
PUMP_DIMENSIONS = ["mcap_group", "sector", "btc_trend", "overall"]


def calculate_pump_condition_scores():
    log.info("Calculating pump condition scores (Option B)...")
    conn = db.get_conn()

    for timeframe in TIMEFRAMES:
        threshold = PUMP_THRESHOLDS.get(timeframe, 10)
        forward_bars = PUMP_FORWARD_BARS.get(timeframe, 6)

        coins = db.get_all_coins()
        regime = db.get_latest_regime()
        regime_dict = dict(regime) if regime else {}

        condition_stats = {}

        for coin in coins:
            if coin["symbol"] == "BTCUSDT":
                continue
            candles_raw = db.get_candles(coin["symbol"], timeframe, 1000)
            if not candles_raw or len(candles_raw) < INDICATOR_WINDOW + forward_bars + 10:
                continue
            candles = [dict(c) for c in reversed(candles_raw)]
            coin_info = dict(coin)
            coin_info.update(regime_dict)

            for i in range(INDICATOR_WINDOW, len(candles) - forward_bars):
                window = candles[i - INDICATOR_WINDOW:i + 1]
                signals = detect_signals(window)
                if not signals:
                    continue

                has_pump = False
                max_pct = 0
                base_price = candles[i]["close"]
                if base_price == 0:
                    continue
                for j in range(1, forward_bars + 1):
                    peak = candles[i + j]["high"]
                    pct = ((peak - base_price) / base_price) * 100
                    if pct > max_pct:
                        max_pct = pct
                    if pct >= threshold:
                        has_pump = True

                dim_values = {
                    "mcap_group": coin_info.get("mcap_group", "200+"),
                    "sector": coin_info.get("sector", "Diger"),
                    "btc_trend": coin_info.get("btc_trend", "yatay"),
                    "overall": "all",
                }

                for cond_name in signals:
                    if cond_name not in CONDITIONS:
                        continue
                    for dim in PUMP_DIMENSIONS:
                        key = (cond_name, timeframe, dim, dim_values[dim])
                        if key not in condition_stats:
                            condition_stats[key] = {"total": 0, "hits": 0, "pct_sum": 0}
                        condition_stats[key]["total"] += 1
                        if has_pump:
                            condition_stats[key]["hits"] += 1
                            condition_stats[key]["pct_sum"] += max_pct

        now = datetime.utcnow().isoformat()
        for (cond, tf, dim, dim_val), stats in condition_stats.items():
            if stats["total"] < SCORE_MIN_SAMPLES:
                continue
            prob = round(stats["hits"] / stats["total"] * 100, 1)
            avg_pct = round(stats["pct_sum"] / stats["hits"], 2) if stats["hits"] > 0 else 0
            conn.execute(
                "INSERT INTO pump_condition_scores "
                "(condition, timeframe, dimension, dimension_value, "
                "total_occurrences, pump_hits, pump_probability, avg_pump_pct, last_updated) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(condition, timeframe, dimension, dimension_value) DO UPDATE SET "
                "total_occurrences=excluded.total_occurrences, pump_hits=excluded.pump_hits, "
                "pump_probability=excluded.pump_probability, avg_pump_pct=excluded.avg_pump_pct, "
                "last_updated=excluded.last_updated",
                [cond, tf, dim, dim_val, stats["total"], stats["hits"], prob, avg_pct, now]
            )

        conn.commit()
    log.info("Pump condition scores complete")


def calculate_all_scores():
    log.info("Calculating scores...")
    conn = db.get_conn()

    for method in ALL_METHODS:
        for timeframe in TIMEFRAMES:
            for dimension in DIMENSIONS:
                if dimension == "overall":
                    _calc_score(conn, method, timeframe, "overall", "all")
                    continue

                values = conn.execute(
                    f"SELECT DISTINCT {dimension} FROM method_signals "
                    f"WHERE method_name=? AND timeframe=? AND {dimension} IS NOT NULL",
                    (method, timeframe)
                ).fetchall()

                for row in values:
                    val = row[0]
                    if val:
                        _calc_score(conn, method, timeframe, dimension, val)

    conn.commit()
    log.info("Score calculation complete")


def _calc_score(conn, method, timeframe, dimension, dim_value):
    if dimension == "overall":
        where = "method_name=? AND timeframe=?"
        params = [method, timeframe]
    else:
        where = f"method_name=? AND timeframe=? AND {dimension}=?"
        params = [method, timeframe, dim_value]

    row = conn.execute(
        f"SELECT COUNT(*) as total, "
        f"SUM(is_success_1d) as w1, SUM(is_success_3d) as w3, SUM(is_success_7d) as w7, "
        f"COUNT(is_success_1d) as c1, COUNT(is_success_3d) as c3, COUNT(is_success_7d) as c7, "
        f"AVG(pct_change_1d) as avg1, AVG(pct_change_3d) as avg3, AVG(pct_change_7d) as avg7, "
        f"MIN(pct_change_7d) as maxdd "
        f"FROM method_signals WHERE {where}",
        params
    ).fetchone()

    total = row[0] or 0
    if total < SCORE_MIN_SAMPLES:
        return

    c1 = row[4] or 1
    c3 = row[5] or 1
    c7 = row[6] or 1

    score = {
        "method_name": method,
        "timeframe": timeframe,
        "dimension": dimension,
        "dimension_value": dim_value,
        "total_signals": total,
        "win_count_1d": row[1] or 0,
        "win_count_3d": row[2] or 0,
        "win_count_7d": row[3] or 0,
        "win_rate_1d": round((row[1] or 0) / c1 * 100, 1),
        "win_rate_3d": round((row[2] or 0) / c3 * 100, 1),
        "win_rate_7d": round((row[3] or 0) / c7 * 100, 1),
        "avg_return_1d": round(row[7] or 0, 2),
        "avg_return_3d": round(row[8] or 0, 2),
        "avg_return_7d": round(row[9] or 0, 2),
        "max_drawdown": round(row[10] or 0, 2),
        "last_updated": datetime.utcnow().isoformat(),
    }
    cols = ", ".join(score.keys())
    placeholders = ", ".join(["?"] * len(score))
    updates = ", ".join(f"{k}=excluded.{k}" for k in score if k not in
                        ("method_name", "timeframe", "dimension", "dimension_value"))
    conn.execute(
        f"INSERT INTO method_scores ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(method_name, timeframe, dimension, dimension_value) DO UPDATE SET {updates}",
        list(score.values())
    )

import json
import time
import logging
from datetime import datetime
from config import (
    PUMP_THRESHOLD_PCT, PUMP_LOOKBACK_HOURS, SCORE_MIN_SAMPLES, TIMEFRAMES,
    TIMEFRAME_MINUTES
)
import database as db
from indicators import detect_signals, get_indicator_snapshot

log = logging.getLogger(__name__)

ALL_METHODS = [
    "rsi", "macd", "ema_20_50", "ema_50_200",
    "bb_squeeze", "bb_breakout", "volume_spike",
    "accumulation", "multi_signal", "whale_activity"
]

DIMENSIONS = [
    "btc_trend", "dominance_trend", "mcap_group",
    "sector", "volatility_class", "volume_profile",
    "btc_correlation_group", "fear_greed_label", "overall"
]


def find_pumps(candles, timeframe):
    if len(candles) < 30:
        return []
    pumps = []
    tf_minutes = TIMEFRAME_MINUTES.get(timeframe, 60)

    for i in range(10, len(candles) - 1):
        lookback = min(6, i)
        base_price = min(c["close"] for c in candles[i - lookback:i])
        if base_price == 0:
            continue
        peak_price = candles[i]["high"]
        pct_change = ((peak_price - base_price) / base_price) * 100

        if pct_change >= PUMP_THRESHOLD_PCT:
            pumps.append({
                "index": i,
                "pump_time": candles[i]["open_time"],
                "pump_pct": round(pct_change, 2),
                "price_before": base_price,
                "price_peak": peak_price,
            })
    return pumps


def analyze_pump_preconditions(candles, pump_index, timeframe):
    lookback_bars = {}
    tf_minutes = TIMEFRAME_MINUTES.get(timeframe, 60)
    for hours in PUMP_LOOKBACK_HOURS:
        bars = max(1, int((hours * 60) / tf_minutes))
        lookback_bars[f"{hours}h"] = bars

    results = {}
    for label, bars in lookback_bars.items():
        start = max(0, pump_index - bars)
        pre_candles = candles[start:pump_index]
        if len(pre_candles) < 5:
            continue
        snapshot = get_indicator_snapshot(pre_candles)
        signals = detect_signals(pre_candles)
        results[label] = {
            "snapshot": snapshot,
            "signals": list(signals.keys()),
            "signal_count": len(signals),
        }
    return results


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
            # Pick the best available lookback (longest with data)
            best_pre = {}
            for key in ["24h", "12h", "4h", "1h"]:
                if key in pre and pre[key].get("snapshot"):
                    best_pre = pre[key]
                    break
            snap = best_pre.get("snapshot", {})
            sigs = best_pre.get("signals", [])
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
                "pre_rsi": snap.get("rsi"),
                "pre_macd_signal": snap.get("macd_signal"),
                "pre_ema_cross": snap.get("ema_cross"),
                "pre_bb_squeeze": 1 if snap.get("bb_squeeze") else 0,
                "pre_volume_ratio": snap.get("volume_ratio"),
                "pre_accumulation": 1 if "accumulation" in sigs else 0,
                "indicators_json": json.dumps(pre),
            }
            db.save_pump(pump_record)

    return results


def run_full_backtest():
    log.info("Running full backtest...")
    coins = db.get_all_coins()
    regime = db.get_latest_regime()
    regime_dict = dict(regime) if regime else {}

    total_signals = 0
    for coin in coins:
        if coin["symbol"] == "BTCUSDT":
            continue
        coin_info = dict(coin)
        coin_info.update(regime_dict)
        signals = run_backtest_for_symbol(coin["symbol"], coin_info)
        for sig in signals:
            db.save_signal(sig)
        total_signals += len(signals)

    log.info(f"Backtest complete: {total_signals} signals recorded")
    calculate_all_scores()
    return total_signals


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
    db.save_score(score)

import json
from datetime import datetime
from flask import Blueprint, jsonify

import database as db
from market_regime import get_current_regime

dashboard_bp = Blueprint("dashboard", __name__)


def row_to_dict(row):
    if row is None:
        return {}
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]


@dashboard_bp.route("/api/regime")
def api_regime():
    r = get_current_regime()
    return jsonify(r)


@dashboard_bp.route("/api/scores")
def api_scores():
    from flask import request
    method = request.args.get("method")
    tf = request.args.get("timeframe")
    dim = request.args.get("dimension")
    dim_val = request.args.get("dimension_value")
    rows = db.get_scores(method_name=method, timeframe=tf,
                         dimension=dim, dimension_value=dim_val)
    return jsonify(rows_to_list(rows))


@dashboard_bp.route("/api/top-coins")
def api_top_coins():
    r = get_current_regime()
    rows = db.get_top_scored_coins(r, limit=15)
    return jsonify(rows_to_list(rows))


@dashboard_bp.route("/api/pumps")
def api_pumps():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM pumps ORDER BY pump_time DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@dashboard_bp.route("/api/pump-stats")
def api_pump_stats():
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) as cnt FROM pumps").fetchone()["cnt"]
    if total == 0:
        conn.close()
        return jsonify({"total": 0, "conditions": {}})

    stats = {}
    for col, label in [
        ("pre_bb_squeeze", "BB Sıkışma"),
        ("pre_accumulation", "Hacim Birikimi"),
    ]:
        row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM pumps WHERE {col} = 1"
        ).fetchone()
        stats[label] = round(row["cnt"] / total * 100, 1) if total else 0

    for col, label, condition in [
        ("pre_rsi", "RSI Oversold", "pre_rsi < 35"),
        ("pre_rsi", "RSI Nötr", "pre_rsi BETWEEN 35 AND 65"),
        ("pre_volume_ratio", "Hacim Spike (2x+)", "pre_volume_ratio >= 2"),
        ("pre_volume_ratio", "Hacim Spike (3x+)", "pre_volume_ratio >= 3"),
    ]:
        row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM pumps WHERE {condition}"
        ).fetchone()
        stats[label] = round(row["cnt"] / total * 100, 1) if total else 0

    for val in ["yukselis", "dusus", "yatay"]:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM pumps WHERE btc_trend=?", (val,)
        ).fetchone()
        stats[f"BTC {val}"] = round(row["cnt"] / total * 100, 1) if total else 0

    conn.close()
    return jsonify({"total": total, "conditions": stats})


@dashboard_bp.route("/api/sectors")
def api_sectors():
    methods = ["rsi", "macd", "ema_20_50", "bb_squeeze", "volume_spike", "multi_signal"]
    sectors = ["L1", "L2", "DeFi", "AI", "Meme", "Gaming"]
    result = {}
    for sector in sectors:
        result[sector] = {}
        for method in methods:
            scores = db.get_scores(method_name=method, dimension="sector", dimension_value=sector)
            if scores:
                result[sector][method] = round(scores[0]["win_rate_7d"], 1)
            else:
                result[sector][method] = None
    return jsonify(result)


@dashboard_bp.route("/api/mcap-scores")
def api_mcap_scores():
    methods = ["rsi", "macd", "ema_20_50", "bb_squeeze", "volume_spike", "multi_signal"]
    groups = ["top50", "51-100", "101-200", "200+"]
    result = {}
    for group in groups:
        result[group] = {}
        for method in methods:
            scores = db.get_scores(method_name=method, dimension="mcap_group", dimension_value=group)
            if scores:
                result[group][method] = round(scores[0]["win_rate_7d"], 1)
            else:
                result[group][method] = None
    return jsonify(result)


@dashboard_bp.route("/api/timeframe-scores")
def api_tf_scores():
    methods = ["rsi", "macd", "ema_20_50", "bb_squeeze", "volume_spike", "multi_signal"]
    timeframes = ["1h", "4h", "1d"]
    result = {}
    for tf in timeframes:
        result[tf] = {}
        for method in methods:
            scores = db.get_scores(method_name=method, timeframe=tf,
                                   dimension="overall", dimension_value="all")
            if scores:
                result[tf][method] = round(scores[0]["win_rate_7d"], 1)
            else:
                result[tf][method] = None
    return jsonify(result)


@dashboard_bp.route("/api/coins")
def api_coins():
    rows = db.get_all_coins()
    return jsonify(rows_to_list(rows)[:50])


@dashboard_bp.route("/api/whale-alerts")
def api_whale_alerts():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM whale_alerts ORDER BY detected_time DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@dashboard_bp.route("/api/whale-stats")
def api_whale_stats():
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) as cnt FROM whale_alerts").fetchone()["cnt"]
    if total == 0:
        conn.close()
        return jsonify({"total": 0, "avg_ratio": 0, "positive_pct": 0})
    positive = conn.execute(
        "SELECT COUNT(*) as cnt FROM whale_alerts WHERE pct_change_24h > 0"
    ).fetchone()["cnt"]
    avg_ratio = conn.execute(
        "SELECT AVG(ratio) as avg FROM whale_alerts"
    ).fetchone()["avg"] or 0
    avg_return = conn.execute(
        "SELECT AVG(pct_change_24h) as avg FROM whale_alerts WHERE pct_change_24h IS NOT NULL"
    ).fetchone()["avg"] or 0
    conn.close()
    return jsonify({
        "total": total,
        "avg_ratio": round(avg_ratio, 1),
        "positive_pct": round(positive / total * 100, 1) if total else 0,
        "avg_return_24h": round(avg_return, 2),
    })


@dashboard_bp.route("/api/correlation-breaks")
def api_corr_breaks():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM correlation_breaks ORDER BY detected_time DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@dashboard_bp.route("/api/correlation-stats")
def api_corr_stats():
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) as cnt FROM correlation_breaks").fetchone()["cnt"]
    if total == 0:
        conn.close()
        return jsonify({"total": 0, "positive_pct": 0, "avg_diff": 0})
    positive = conn.execute(
        "SELECT COUNT(*) as cnt FROM correlation_breaks WHERE pct_change_7d > 0"
    ).fetchone()["cnt"]
    avg_diff = conn.execute(
        "SELECT AVG(corr_diff) as avg FROM correlation_breaks"
    ).fetchone()["avg"] or 0
    avg_return = conn.execute(
        "SELECT AVG(pct_change_7d) as avg FROM correlation_breaks WHERE pct_change_7d IS NOT NULL"
    ).fetchone()["avg"] or 0
    # By sector
    sectors = conn.execute(
        "SELECT sector, COUNT(*) as cnt, AVG(pct_change_7d) as avg_ret "
        "FROM correlation_breaks GROUP BY sector ORDER BY cnt DESC"
    ).fetchall()
    conn.close()
    return jsonify({
        "total": total,
        "positive_pct": round(positive / total * 100, 1) if total else 0,
        "avg_diff": round(avg_diff, 3),
        "avg_return_7d": round(avg_return, 2),
        "by_sector": [{"sector": r["sector"], "count": r["cnt"],
                       "avg_return": round(r["avg_ret"] or 0, 2)} for r in sectors],
    })


@dashboard_bp.route("/api/leader-follower")
def api_leader_follower():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT sector, leader_symbol, follower_symbol, "
        "AVG(follower_delay_hours) as avg_delay, "
        "AVG(follower_move_pct) as avg_move, "
        "COUNT(*) as cnt "
        "FROM sector_leaders "
        "GROUP BY sector, leader_symbol, follower_symbol "
        "HAVING cnt >= 2 "
        "ORDER BY sector, avg_delay"
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@dashboard_bp.route("/api/leader-follower-summary")
def api_lf_summary():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT sector, "
        "AVG(follower_delay_hours) as avg_delay, "
        "AVG(ABS(follower_move_pct)) as avg_move, "
        "COUNT(*) as total_patterns "
        "FROM sector_leaders "
        "GROUP BY sector "
        "ORDER BY avg_delay"
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@dashboard_bp.route("/api/status")
def api_status():
    conn = db.get_conn()
    coin_count = conn.execute("SELECT COUNT(*) as cnt FROM coins").fetchone()["cnt"]
    candle_count = conn.execute("SELECT COUNT(*) as cnt FROM candles").fetchone()["cnt"]
    signal_count = conn.execute("SELECT COUNT(*) as cnt FROM method_signals").fetchone()["cnt"]
    score_count = conn.execute("SELECT COUNT(*) as cnt FROM method_scores").fetchone()["cnt"]
    pump_count = conn.execute("SELECT COUNT(*) as cnt FROM pumps").fetchone()["cnt"]
    whale_count = conn.execute("SELECT COUNT(*) as cnt FROM whale_alerts").fetchone()["cnt"]
    corr_count = conn.execute("SELECT COUNT(*) as cnt FROM correlation_breaks").fetchone()["cnt"]
    lf_count = conn.execute("SELECT COUNT(*) as cnt FROM sector_leaders").fetchone()["cnt"]
    conn.close()
    return jsonify({
        "coins": coin_count,
        "candles": candle_count,
        "signals": signal_count,
        "scores": score_count,
        "pumps": pump_count,
        "whales": whale_count,
        "corr_breaks": corr_count,
        "leader_follower": lf_count,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    })

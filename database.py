import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "crypto_research.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS coins (
            symbol TEXT PRIMARY KEY,
            base_asset TEXT,
            mcap_rank INTEGER,
            mcap_group TEXT,
            sector TEXT,
            volatility_class TEXT,
            volume_profile TEXT,
            btc_correlation_group TEXT,
            btc_correlation REAL,
            avg_daily_volume REAL,
            last_classified TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL,
            quote_volume REAL,
            num_trades INTEGER DEFAULT 0,
            PRIMARY KEY (symbol, timeframe, open_time)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS market_regimes (
            timestamp INTEGER PRIMARY KEY,
            btc_price REAL,
            btc_trend TEXT,
            btc_dominance REAL,
            dominance_trend TEXT,
            total_volume REAL,
            volume_status TEXT,
            fear_greed_value INTEGER,
            fear_greed_label TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS method_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            method_name TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            signal_time INTEGER NOT NULL,
            signal_type TEXT,
            price_at_signal REAL,
            price_after_1d REAL,
            price_after_3d REAL,
            price_after_7d REAL,
            pct_change_1d REAL,
            pct_change_3d REAL,
            pct_change_7d REAL,
            btc_trend TEXT,
            dominance_trend TEXT,
            mcap_group TEXT,
            sector TEXT,
            volatility_class TEXT,
            volume_profile TEXT,
            btc_correlation_group TEXT,
            fear_greed_label TEXT,
            is_success_1d INTEGER,
            is_success_3d INTEGER,
            is_success_7d INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS method_scores (
            method_name TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            dimension TEXT NOT NULL,
            dimension_value TEXT NOT NULL,
            total_signals INTEGER DEFAULT 0,
            win_count_1d INTEGER DEFAULT 0,
            win_count_3d INTEGER DEFAULT 0,
            win_count_7d INTEGER DEFAULT 0,
            win_rate_1d REAL DEFAULT 0,
            win_rate_3d REAL DEFAULT 0,
            win_rate_7d REAL DEFAULT 0,
            avg_return_1d REAL DEFAULT 0,
            avg_return_3d REAL DEFAULT 0,
            avg_return_7d REAL DEFAULT 0,
            max_drawdown REAL DEFAULT 0,
            last_updated TEXT,
            PRIMARY KEY (method_name, timeframe, dimension, dimension_value)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS pumps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            pump_time INTEGER NOT NULL,
            pump_pct REAL,
            price_before REAL,
            price_peak REAL,
            btc_trend TEXT,
            dominance_trend TEXT,
            mcap_group TEXT,
            sector TEXT,
            pre_rsi REAL,
            pre_macd_signal TEXT,
            pre_ema_cross TEXT,
            pre_bb_squeeze INTEGER,
            pre_volume_ratio REAL,
            pre_accumulation INTEGER,
            indicators_json TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS whale_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            detected_time INTEGER NOT NULL,
            avg_trade_size REAL,
            normal_avg_trade_size REAL,
            ratio REAL,
            price_at_detection REAL,
            price_after_24h REAL,
            pct_change_24h REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS correlation_breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            detected_time INTEGER NOT NULL,
            corr_30d REAL,
            corr_48h REAL,
            corr_diff REAL,
            price_at_detection REAL,
            price_after_7d REAL,
            pct_change_7d REAL,
            btc_trend TEXT,
            sector TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sector_leaders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sector TEXT NOT NULL,
            leader_symbol TEXT NOT NULL,
            leader_move_pct REAL,
            leader_move_time INTEGER,
            follower_symbol TEXT NOT NULL,
            follower_move_pct REAL,
            follower_delay_hours REAL,
            timeframe TEXT
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_candles_sym_tf ON candles(symbol, timeframe)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_signals_method ON method_signals(method_name, timeframe)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON method_signals(symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pumps_symbol ON pumps(symbol)")

    conn.commit()
    conn.close()


def save_candles(symbol, timeframe, candles_data):
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(symbol, timeframe, c[0], c[1], c[2], c[3], c[4], c[5], c[7], c[8] if len(c) > 8 else 0) for c in candles_data]
    )
    conn.commit()
    conn.close()


def get_candles(symbol, timeframe, limit=500):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM candles WHERE symbol=? AND timeframe=? ORDER BY open_time DESC LIMIT ?",
        (symbol, timeframe, limit)
    ).fetchall()
    conn.close()
    return rows


def save_coin(symbol, base_asset, **kwargs):
    conn = get_conn()
    existing = conn.execute("SELECT * FROM coins WHERE symbol=?", (symbol,)).fetchone()
    if existing:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [symbol]
        conn.execute(f"UPDATE coins SET {sets} WHERE symbol=?", vals)
    else:
        conn.execute(
            "INSERT INTO coins (symbol, base_asset) VALUES (?,?)",
            (symbol, base_asset)
        )
        if kwargs:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            vals = list(kwargs.values()) + [symbol]
            conn.execute(f"UPDATE coins SET {sets} WHERE symbol=?", vals)
    conn.commit()
    conn.close()


def get_all_coins():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM coins ORDER BY mcap_rank").fetchall()
    conn.close()
    return rows


def save_regime(timestamp, **kwargs):
    conn = get_conn()
    cols = ", ".join(["timestamp"] + list(kwargs.keys()))
    placeholders = ", ".join(["?"] * (1 + len(kwargs)))
    conn.execute(
        f"INSERT OR REPLACE INTO market_regimes ({cols}) VALUES ({placeholders})",
        [timestamp] + list(kwargs.values())
    )
    conn.commit()
    conn.close()


def get_latest_regime():
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM market_regimes ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def save_signal(signal_dict):
    conn = get_conn()
    cols = ", ".join(signal_dict.keys())
    placeholders = ", ".join(["?"] * len(signal_dict))
    conn.execute(
        f"INSERT INTO method_signals ({cols}) VALUES ({placeholders})",
        list(signal_dict.values())
    )
    conn.commit()
    conn.close()


def save_score(score_dict):
    conn = get_conn()
    cols = ", ".join(score_dict.keys())
    placeholders = ", ".join(["?"] * len(score_dict))
    updates = ", ".join(f"{k}=excluded.{k}" for k in score_dict if k not in
                        ("method_name", "timeframe", "dimension", "dimension_value"))
    conn.execute(
        f"INSERT INTO method_scores ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(method_name, timeframe, dimension, dimension_value) DO UPDATE SET {updates}",
        list(score_dict.values())
    )
    conn.commit()
    conn.close()


def get_scores(method_name=None, timeframe=None, dimension=None, dimension_value=None):
    conn = get_conn()
    query = "SELECT * FROM method_scores WHERE 1=1"
    params = []
    if method_name:
        query += " AND method_name=?"
        params.append(method_name)
    if timeframe:
        query += " AND timeframe=?"
        params.append(timeframe)
    if dimension:
        query += " AND dimension=?"
        params.append(dimension)
    if dimension_value:
        query += " AND dimension_value=?"
        params.append(dimension_value)
    query += " ORDER BY win_rate_7d DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def save_pump(pump_dict):
    conn = get_conn()
    cols = ", ".join(pump_dict.keys())
    placeholders = ", ".join(["?"] * len(pump_dict))
    conn.execute(f"INSERT INTO pumps ({cols}) VALUES ({placeholders})", list(pump_dict.values()))
    conn.commit()
    conn.close()


def get_top_scored_coins(regime_dict, limit=10):
    conn = get_conn()
    rows = conn.execute("""
        SELECT ms.symbol, ms.method_name, ms.timeframe,
               c.mcap_group, c.sector,
               sc.win_rate_7d, sc.avg_return_7d, sc.total_signals
        FROM method_signals ms
        JOIN coins c ON ms.symbol = c.symbol
        JOIN method_scores sc ON ms.method_name = sc.method_name
            AND ms.timeframe = sc.timeframe
            AND sc.dimension = 'btc_trend'
            AND sc.dimension_value = ?
        WHERE ms.signal_time = (
            SELECT MAX(signal_time) FROM method_signals ms2
            WHERE ms2.symbol = ms.symbol AND ms2.method_name = ms.method_name
        )
        AND sc.total_signals >= ?
        ORDER BY sc.win_rate_7d DESC
        LIMIT ?
    """, (regime_dict.get("btc_trend", "yatay"), 5, limit)).fetchall()
    conn.close()
    return rows

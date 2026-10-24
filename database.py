import os
import logging
import threading
from config import TURSO_DB_URL, TURSO_AUTH_TOKEN

DB_PATH = os.path.join(os.path.dirname(__file__), "crypto_research.db")

_conn = None
_sync_lock = threading.Lock()
_conn_lock = threading.Lock()


class DictCursor:
    """Wrapper that makes cursor results behave like dicts."""
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def _to_dict(self, row):
        if row is None:
            return None
        cols = [d[0] for d in self._cursor.description]
        return dict(zip(cols, row))

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._to_dict(row)

    def fetchall(self):
        return [self._to_dict(r) for r in self._cursor.fetchall()]


class DictConnection:
    """Wrapper around a libsql/sqlite3 connection that returns dicts."""
    def __init__(self, conn):
        self._conn = conn

    def _run_with_lock(self, fn):
        with _conn_lock:
            try:
                return fn()
            except (ValueError, Exception) as e:
                err_str = str(e).lower()
                if "stream" in err_str and ("not found" in err_str or "already in use" in err_str):
                    log.warning(f"Turso stream error, reconnecting: {e}")
                    _reconnect()
                    self._conn = _conn._conn
                    return fn()
                raise

    def execute(self, sql, params=None):
        def fn():
            if params is not None:
                cur = self._conn.execute(sql, tuple(params))
            else:
                cur = self._conn.execute(sql)
            return DictCursor(cur)
        return self._run_with_lock(fn)

    def executemany(self, sql, params):
        def fn():
            return self._conn.executemany(sql, [tuple(p) for p in params])
        return self._run_with_lock(fn)

    def commit(self):
        self._conn.commit()

    def sync(self):
        if hasattr(self._conn, 'sync'):
            with _sync_lock:
                self._conn.sync()


log = logging.getLogger(__name__)


def _create_connection():
    if TURSO_DB_URL and TURSO_AUTH_TOKEN:
        import libsql_experimental as libsql
        raw = libsql.connect(
            DB_PATH,
            sync_url=TURSO_DB_URL,
            auth_token=TURSO_AUTH_TOKEN
        )
        import time
        for attempt in range(5):
            try:
                raw.sync()
                log.info("Turso sync successful")
                break
            except Exception as e:
                log.warning(f"Turso sync attempt {attempt+1}/5 failed: {e}")
                time.sleep(2 ** attempt)
        else:
            log.error("All Turso sync attempts failed — starting with empty local DB")
    else:
        import sqlite3
        raw = sqlite3.connect(DB_PATH)

    conn = DictConnection(raw)
    conn._conn.execute("PRAGMA journal_mode=WAL")
    conn._conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _reconnect():
    global _conn
    log.info("Reconnecting to database...")
    _conn = _create_connection()
    log.info("Database reconnected")


def get_conn():
    global _conn
    if _conn is not None:
        return _conn
    _conn = _create_connection()
    return _conn


def sync_db():
    if _conn:
        try:
            _conn.sync()
        except Exception as e:
            log.warning(f"Turso sync failed: {e}")


def init_db():
    conn = get_conn()

    conn.execute("""
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

    conn.execute("""
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

    conn.execute("""
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

    conn.execute("""
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

    conn.execute("""
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

    conn.execute("""
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
            pre_rsi_divergence INTEGER DEFAULT 0,
            pre_obv_trend INTEGER DEFAULT 0,
            pre_stoch_rsi INTEGER DEFAULT 0,
            pre_macd_cross INTEGER DEFAULT 0,
            pre_ema_cross_signal INTEGER DEFAULT 0,
            pre_volume_spike INTEGER DEFAULT 0,
            pre_multi_signal INTEGER DEFAULT 0,
            indicators_json TEXT
        )
    """)

    conn.execute("""
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

    conn.execute("""
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

    conn.execute("""
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS pump_condition_scores (
            condition TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            dimension TEXT NOT NULL,
            dimension_value TEXT NOT NULL,
            total_occurrences INTEGER DEFAULT 0,
            pump_hits INTEGER DEFAULT 0,
            pump_probability REAL DEFAULT 0,
            avg_pump_pct REAL DEFAULT 0,
            last_updated TEXT,
            PRIMARY KEY (condition, timeframe, dimension, dimension_value)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS pump_notifications (
            symbol TEXT NOT NULL,
            pump_time TEXT NOT NULL,
            notified_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (symbol, pump_time)
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_sym_tf ON candles(symbol, timeframe)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_method ON method_signals(method_name, timeframe)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON method_signals(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pumps_symbol ON pumps(symbol)")

    for col in ["pre_rsi_divergence", "pre_obv_trend", "pre_stoch_rsi",
                 "pre_macd_cross", "pre_ema_cross_signal", "pre_volume_spike", "pre_multi_signal"]:
        try:
            conn.execute(f"ALTER TABLE pumps ADD COLUMN {col} INTEGER DEFAULT 0")
        except Exception:
            pass

    conn.commit()
    sync_db()


def save_candles(symbol, timeframe, candles_data):
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(symbol, timeframe, c[0], c[1], c[2], c[3], c[4], c[5], c[7], c[8] if len(c) > 8 else 0) for c in candles_data]
    )
    conn.commit()


def get_candles(symbol, timeframe, limit=500):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM candles WHERE symbol=? AND timeframe=? ORDER BY open_time DESC LIMIT ?",
        (symbol, timeframe, limit)
    ).fetchall()
    return rows


def save_coin(symbol, base_asset, **kwargs):
    conn = get_conn()
    existing = conn.execute("SELECT * FROM coins WHERE symbol=?", (symbol,)).fetchone()
    if existing:
        if kwargs:
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


def get_all_coins():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM coins ORDER BY mcap_rank").fetchall()
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


def get_latest_regime():
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM market_regimes ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
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
    return rows


def save_pump(pump_dict):
    conn = get_conn()
    cols = ", ".join(pump_dict.keys())
    placeholders = ", ".join(["?"] * len(pump_dict))
    conn.execute(f"INSERT INTO pumps ({cols}) VALUES ({placeholders})", list(pump_dict.values()))
    conn.commit()


def get_top_scored_coins(regime_dict, limit=10):
    if not regime_dict:
        return []
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
    return rows

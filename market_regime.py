import time
import logging
import database as db
from data_collector import fetch_btc_price, fetch_btc_dominance, fetch_total_market_volume, fetch_fear_greed

log = logging.getLogger(__name__)


def detect_btc_trend(candles):
    if len(candles) < 50:
        return "yatay"
    closes = [c["close"] for c in candles[-50:]]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    if not ema20 or not ema50:
        return "yatay"

    current_price = closes[-1]
    if ema20[-1] > ema50[-1] and current_price > ema20[-1]:
        return "yukselis"
    elif ema20[-1] < ema50[-1] and current_price < ema20[-1]:
        return "dusus"
    return "yatay"


def detect_dominance_trend(current_dom, candles_btc):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT btc_dominance FROM market_regimes WHERE btc_dominance IS NOT NULL ORDER BY timestamp DESC LIMIT 7"
    ).fetchall()
    if not rows or len(rows) < 2:
        return "sabit"
    old_dom = rows[-1]["btc_dominance"]
    if not old_dom or old_dom == 0:
        return "sabit"
    pct = ((current_dom - old_dom) / old_dom) * 100
    if pct > 1:
        return "artiyor"
    elif pct < -1:
        return "azaliyor"
    return "sabit"


def detect_volume_status(total_volume, candles_btc):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT total_volume FROM market_regimes WHERE total_volume IS NOT NULL AND total_volume > 0 ORDER BY timestamp DESC LIMIT 30"
    ).fetchall()
    if rows and len(rows) >= 5:
        avg_vol = sum(r["total_volume"] for r in rows) / len(rows)
        if avg_vol > 0:
            ratio = total_volume / avg_vol
            if ratio > 1.5:
                return "yuksek"
            elif ratio < 0.7:
                return "dusuk"
            return "normal"
    return "normal"


def classify_fear_greed(value):
    if value <= 20:
        return "asiri_korku"
    elif value <= 40:
        return "korku"
    elif value <= 60:
        return "notr"
    elif value <= 80:
        return "acgozluluk"
    return "asiri_acgozluluk"


async def update_regime(session):
    log.info("Updating market regime...")

    btc_price = await fetch_btc_price(session)
    btc_dom = await fetch_btc_dominance(session)
    total_vol = await fetch_total_market_volume(session)
    fg = await fetch_fear_greed(session)

    btc_candles_raw = db.get_candles("BTCUSDT", "1d", 60)
    btc_candles = [dict(c) for c in reversed(btc_candles_raw)]

    btc_trend = detect_btc_trend(btc_candles)
    dom_trend = detect_dominance_trend(btc_dom, btc_candles)
    vol_status = detect_volume_status(total_vol, btc_candles)
    fg_label = classify_fear_greed(fg["value"])

    now = int(time.time())
    db.save_regime(
        now,
        btc_price=btc_price,
        btc_trend=btc_trend,
        btc_dominance=btc_dom,
        dominance_trend=dom_trend,
        total_volume=total_vol,
        volume_status=vol_status,
        fear_greed_value=fg["value"],
        fear_greed_label=fg_label,
    )

    log.info(f"Regime: BTC={btc_trend}, Dom={dom_trend}, Vol={vol_status}, FG={fg_label}")
    return {
        "btc_price": btc_price,
        "btc_trend": btc_trend,
        "btc_dominance": btc_dom,
        "dominance_trend": dom_trend,
        "total_volume": total_vol,
        "volume_status": vol_status,
        "fear_greed_value": fg["value"],
        "fear_greed_label": fg_label,
    }


def get_current_regime():
    row = db.get_latest_regime()
    if row:
        return dict(row)
    return {
        "btc_trend": "yatay",
        "dominance_trend": "sabit",
        "volume_status": "normal",
        "fear_greed_label": "notr",
        "btc_price": 0,
        "btc_dominance": 0,
        "fear_greed_value": 50,
    }


def _ema(data, period):
    if len(data) < period:
        return []
    multiplier = 2 / (period + 1)
    ema_vals = [sum(data[:period]) / period]
    for price in data[period:]:
        ema_vals.append((price - ema_vals[-1]) * multiplier + ema_vals[-1])
    return ema_vals

import logging
from config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT, BB_SQUEEZE_THRESHOLD,
    VOLUME_SPIKE_MULTIPLIER, ACCUMULATION_VOL_MIN,
    ACCUMULATION_VOL_MAX, ACCUMULATION_PRICE_MAX_CHANGE
)

log = logging.getLogger(__name__)


def ema(data, period):
    if len(data) < period:
        return []
    mult = 2 / (period + 1)
    vals = [sum(data[:period]) / period]
    for p in data[period:]:
        vals.append((p - vals[-1]) * mult + vals[-1])
    return vals


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_vals = []

    if avg_loss == 0:
        rsi_vals.append(100)
    else:
        rs = avg_gain / avg_loss
        rsi_vals.append(100 - (100 / (1 + rs)))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_vals.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(100 - (100 / (1 + rs)))

    return rsi_vals


def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return [], [], []
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
    signal_line = ema(macd_line, signal)

    offset2 = len(macd_line) - len(signal_line)
    histogram = [macd_line[i + offset2] - signal_line[i] for i in range(len(signal_line))]

    return macd_line, signal_line, histogram


def bollinger_bands(closes, period=20, std_dev=2):
    if len(closes) < period:
        return [], [], []
    upper, middle, lower = [], [], []
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        avg = sum(window) / period
        variance = sum((x - avg) ** 2 for x in window) / period
        std = variance ** 0.5
        middle.append(avg)
        upper.append(avg + std_dev * std)
        lower.append(avg - std_dev * std)
    return upper, middle, lower


def bb_squeeze(upper, lower, middle):
    if not upper or not middle or middle[-1] == 0:
        return False
    bandwidth = (upper[-1] - lower[-1]) / middle[-1]
    return bandwidth < BB_SQUEEZE_THRESHOLD


def detect_signals(candles):
    if len(candles) < 60:
        return {}

    closes = [c["close"] for c in candles]
    volumes = [c["quote_volume"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    signals = {}

    # RSI
    rsi_vals = rsi(closes)
    if rsi_vals:
        current_rsi = rsi_vals[-1]
        if current_rsi <= RSI_OVERSOLD:
            signals["rsi"] = {"type": "oversold", "value": round(current_rsi, 1)}
        elif current_rsi >= RSI_OVERBOUGHT:
            signals["rsi"] = {"type": "overbought", "value": round(current_rsi, 1)}

    # MACD crossover
    macd_line, signal_line, hist = macd(closes)
    if len(hist) >= 2:
        if hist[-1] > 0 and hist[-2] <= 0:
            signals["macd"] = {"type": "bullish_cross", "value": round(hist[-1], 6)}
        elif hist[-1] < 0 and hist[-2] >= 0:
            signals["macd"] = {"type": "bearish_cross", "value": round(hist[-1], 6)}

    # EMA 20/50
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    if len(ema20) >= 2 and len(ema50) >= 2:
        curr_diff = ema20[-1] - ema50[-1]
        prev_diff = ema20[-2] - ema50[-2]
        if curr_diff > 0 and prev_diff <= 0:
            signals["ema_20_50"] = {"type": "golden_cross", "value": round(curr_diff, 6)}
        elif curr_diff < 0 and prev_diff >= 0:
            signals["ema_20_50"] = {"type": "death_cross", "value": round(curr_diff, 6)}

    # EMA 50/200
    ema200 = ema(closes, 200) if len(closes) >= 200 else []
    if len(ema50) >= 2 and len(ema200) >= 2:
        curr_diff = ema50[-1] - ema200[-1]
        prev_diff = ema50[-2] - ema200[-2]
        if curr_diff > 0 and prev_diff <= 0:
            signals["ema_50_200"] = {"type": "golden_cross", "value": round(curr_diff, 6)}
        elif curr_diff < 0 and prev_diff >= 0:
            signals["ema_50_200"] = {"type": "death_cross", "value": round(curr_diff, 6)}

    # Bollinger squeeze
    bb_upper, bb_mid, bb_lower = bollinger_bands(closes)
    if bb_upper:
        is_squeeze = bb_squeeze(bb_upper, bb_lower, bb_mid)
        if is_squeeze:
            signals["bb_squeeze"] = {"type": "squeeze", "value": round((bb_upper[-1] - bb_lower[-1]) / bb_mid[-1], 4)}
        if closes[-1] > bb_upper[-1]:
            signals["bb_breakout"] = {"type": "upper_breakout", "value": round(closes[-1] - bb_upper[-1], 6)}
        elif closes[-1] < bb_lower[-1]:
            signals["bb_breakout"] = {"type": "lower_breakout", "value": round(closes[-1] - bb_lower[-1], 6)}

    # Volume spike
    if len(volumes) >= 21:
        avg_vol = sum(volumes[-21:-1]) / 20
        if avg_vol > 0 and volumes[-1] > avg_vol * VOLUME_SPIKE_MULTIPLIER:
            signals["volume_spike"] = {
                "type": "spike",
                "value": round(volumes[-1] / avg_vol, 1)
            }

    # Accumulation detection
    if len(volumes) >= 7 and len(closes) >= 7:
        recent_vols = volumes[-6:]
        avg_vol_30 = sum(volumes[-30:-6]) / max(1, len(volumes[-30:-6]))
        if avg_vol_30 > 0:
            vol_ratios = [v / avg_vol_30 for v in recent_vols]
            avg_ratio = sum(vol_ratios) / len(vol_ratios)
            price_change = abs((closes[-1] - closes[-6]) / closes[-6] * 100) if closes[-6] > 0 else 100
            if (ACCUMULATION_VOL_MIN <= avg_ratio <= ACCUMULATION_VOL_MAX
                    and price_change <= ACCUMULATION_PRICE_MAX_CHANGE):
                signals["accumulation"] = {
                    "type": "accumulation",
                    "value": round(avg_ratio, 2),
                    "price_change": round(price_change, 2)
                }

    # Whale activity (avg trade size anomaly)
    if len(candles) >= 31:
        num_trades_list = [c.get("num_trades", 0) for c in candles]
        if num_trades_list[-1] and num_trades_list[-1] > 0:
            current_avg_trade = volumes[-1] / num_trades_list[-1]
            lookback_avgs = []
            for j in range(-31, -1):
                nt = num_trades_list[j] if abs(j) <= len(num_trades_list) else 0
                vol = volumes[j] if abs(j) <= len(volumes) else 0
                if nt > 0:
                    lookback_avgs.append(vol / nt)
            if lookback_avgs:
                normal_avg = sum(lookback_avgs) / len(lookback_avgs)
                if normal_avg > 0:
                    whale_ratio = current_avg_trade / normal_avg
                    if whale_ratio >= 5.0:
                        signals["whale_activity"] = {
                            "type": "large_trades",
                            "value": round(whale_ratio, 1)
                        }

    # Multi-timeframe alignment count
    bullish_count = sum(1 for s in signals.values() if s["type"] in
                        ("oversold", "bullish_cross", "golden_cross", "squeeze", "spike", "accumulation", "large_trades"))
    if bullish_count >= 3:
        signals["multi_signal"] = {"type": "strong_alignment", "value": bullish_count}

    return signals


def get_indicator_snapshot(candles):
    if len(candles) < 30:
        return {}
    closes = [c["close"] for c in candles]
    volumes = [c["quote_volume"] for c in candles]

    snapshot = {}

    rsi_vals = rsi(closes)
    if rsi_vals:
        snapshot["rsi"] = round(rsi_vals[-1], 1)

    _, _, hist = macd(closes)
    if hist:
        snapshot["macd_hist"] = round(hist[-1], 6)
        snapshot["macd_signal"] = "bullish" if hist[-1] > 0 else "bearish"

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    if ema20 and ema50:
        snapshot["ema_20"] = round(ema20[-1], 6)
        snapshot["ema_50"] = round(ema50[-1], 6)
        snapshot["ema_cross"] = "golden" if ema20[-1] > ema50[-1] else "death"

    bb_u, bb_m, bb_l = bollinger_bands(closes)
    if bb_u:
        snapshot["bb_bandwidth"] = round((bb_u[-1] - bb_l[-1]) / bb_m[-1], 4) if bb_m[-1] > 0 else 0
        snapshot["bb_squeeze"] = snapshot["bb_bandwidth"] < BB_SQUEEZE_THRESHOLD

    if len(volumes) >= 21:
        avg_vol = sum(volumes[-21:-1]) / 20
        snapshot["volume_ratio"] = round(volumes[-1] / avg_vol, 2) if avg_vol > 0 else 1

    return snapshot

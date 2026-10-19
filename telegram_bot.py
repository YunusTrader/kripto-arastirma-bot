import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from config import BOT_TOKEN, MY_CHAT_ID, TIMEFRAMES
import database as db
from market_regime import get_current_regime
from indicators import detect_signals, get_indicator_snapshot

log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

users = set()
if MY_CHAT_ID:
    users.add(int(MY_CHAT_ID))
    log.info(f"MY_CHAT_ID configured: {MY_CHAT_ID}")
else:
    log.warning("MY_CHAT_ID not set! Bot won't send broadcast messages until user sends /start")

METHOD_MAP = {
    "ema": "ema_20_50", "macd": "macd",
    "bb": "bb_squeeze", "bollinger": "bb_squeeze",
    "hacim": "volume_spike", "volume": "volume_spike",
    "birikim": "accumulation", "accumulation": "accumulation",
    "multi": "multi_signal", "coklu": "multi_signal",
    "rsi": "rsi_divergence", "rsi_div": "rsi_divergence", "rsi_divergence": "rsi_divergence",
    "obv": "obv_trend", "obv_trend": "obv_trend",
    "stoch": "stoch_rsi", "stoch_rsi": "stoch_rsi", "stochrsi": "stoch_rsi",
    "whale": "whale_activity", "balina": "whale_activity",
}

_last_regime = {"btc_trend": None, "dominance_trend": None}


async def safe_send(chat_id, text, parse_mode="Markdown"):
    try:
        if len(text) <= 4000:
            await bot.send_message(chat_id, text, parse_mode=parse_mode)
        else:
            parts = []
            for line in text.split("\n"):
                if parts and sum(len(p) for p in parts) + len(line) + len(parts) > 3900:
                    await bot.send_message(chat_id, "\n".join(parts), parse_mode=parse_mode)
                    parts = []
                    await asyncio.sleep(0.3)
                parts.append(line)
            if parts:
                await bot.send_message(chat_id, "\n".join(parts), parse_mode=parse_mode)
    except Exception as e:
        log.warning(f"Send error to {chat_id} (trying plain text): {e}")
        try:
            clean = text.replace("*", "").replace("`", "").replace("_", "")
            await bot.send_message(chat_id, clean[:4000])
        except Exception as e2:
            log.error(f"Plain text send also failed to {chat_id}: {e2}")


async def broadcast(text, parse_mode="Markdown"):
    for uid in users:
        await safe_send(uid, text, parse_mode)


# --- COMMANDS ---

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    users.add(m.chat.id)
    await m.answer(
        "Kripto Arastirma Botu baslatildi!\n\n"
        "Komutlar:\n"
        "/rapor - Anlik piyasa raporu\n"
        "/coin SOL - Coin detay analizi\n"
        "/yontem EMA - Yontem performansi\n"
        "/rejim - Piyasa rejimi\n"
        "/top - En yuksek skorlu coinler\n"
        "/top50 - Top 50 mcap analizi\n"
        "/sektor DeFi - Sektor raporu\n"
        "/karsilastir MACD EMA - Yontem karsilastir\n"
        "/whale - Whale/buyuk islem tespitleri\n"
        "/korelasyon - Korelasyon kirilmalari\n"
        "/lider - Sektor lider-takipci analizi\n"
        "/yardim - Bu liste"
    )


@dp.message(Command("yardim"))
async def cmd_help(m: types.Message):
    await cmd_start(m)


@dp.message(Command("rejim"))
async def cmd_regime(m: types.Message):
    r = get_current_regime()
    trend_icon = {"yukselis": "📈", "dusus": "📉", "yatay": "➡️"}.get(r["btc_trend"], "➡️")
    dom_icon = {"artiyor": "📈", "azaliyor": "📉", "sabit": "➡️"}.get(r["dominance_trend"], "➡️")

    text = (
        f"*Mevcut Piyasa Rejimi*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"BTC Fiyat: `${r.get('btc_price', 0):,.0f}`\n"
        f"BTC Trend: {trend_icon} `{r['btc_trend']}`\n"
        f"BTC Dominance: `%{r.get('btc_dominance', 0):.1f}` {dom_icon} `{r['dominance_trend']}`\n"
        f"Hacim Durumu: `{r.get('volume_status', 'normal')}`\n"
        f"Korku/Acgozluluk: `{r.get('fear_greed_value', 50)}` — `{r.get('fear_greed_label', 'notr')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    scores = db.get_scores(dimension="btc_trend", dimension_value=r["btc_trend"])
    if scores:
        text += "\n*Bu rejimde en basarili yontemler:*\n"
        seen = set()
        for s in scores[:5]:
            key = s["method_name"]
            if key in seen:
                continue
            seen.add(key)
            text += f"• `{s['method_name']}` ({s['timeframe']}): %{s['win_rate_7d']:.0f} basari ({s['total_signals']} sinyal)\n"

    await safe_send(m.chat.id, text)


@dp.message(Command("rapor"))
async def cmd_report(m: types.Message):
    r = get_current_regime()
    trend_icon = {"yukselis": "📈", "dusus": "📉", "yatay": "➡️"}.get(r["btc_trend"], "➡️")

    text = (
        f"*Piyasa Raporu*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"BTC: `${r.get('btc_price', 0):,.0f}` {trend_icon}\n"
        f"Dominance: `%{r.get('btc_dominance', 0):.1f}` (`{r['dominance_trend']}`)\n"
        f"Korku/Acgozluluk: `{r.get('fear_greed_value', 50)}` — `{r.get('fear_greed_label', 'notr')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    scores = db.get_scores(dimension="btc_trend", dimension_value=r["btc_trend"])
    if scores:
        text += "\n*En basarili yontemler (bu rejim):*\n"
        seen = set()
        count = 0
        for s in scores:
            key = f"{s['method_name']}_{s['timeframe']}"
            if key in seen:
                continue
            seen.add(key)
            bar = "█" * int(s["win_rate_7d"] / 10) + "░" * (10 - int(s["win_rate_7d"] / 10))
            text += f"`{s['method_name']:15s}` {s['timeframe']:3s} |{bar}| %{s['win_rate_7d']:.0f}\n"
            count += 1
            if count >= 8:
                break

    top_coins = db.get_top_scored_coins(r, limit=5)
    if top_coins:
        text += "\n*One cikan coinler:*\n"
        for i, tc in enumerate(top_coins, 1):
            text += f"`{i}.` `{tc['symbol']:10s}` {tc['method_name']} ({tc['timeframe']}) — %{tc['win_rate_7d']:.0f}\n"

    text += f"\nDetay: /coin [isim] veya /yontem [isim]"
    await safe_send(m.chat.id, text)


@dp.message(Command("coin"))
async def cmd_coin(m: types.Message):
    parts = m.text.strip().split()
    if len(parts) < 2:
        await m.answer("Kullanim: /coin SOL")
        return

    base = parts[1].upper()
    symbol = base if base.endswith("USDT") else f"{base}USDT"

    coins = db.get_all_coins()
    coin = None
    for c in coins:
        if c["symbol"] == symbol:
            coin = dict(c)
            break

    if not coin:
        await m.answer(f"`{symbol}` bulunamadi.")
        return

    r = get_current_regime()

    text = (
        f"*{symbol} Detay Raporu*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Market Cap Grubu: `{coin.get('mcap_group', '?')}` (#{coin.get('mcap_rank', '?')})\n"
        f"Sektor: `{coin.get('sector', '?')}`\n"
        f"Volatilite: `{coin.get('volatility_class', '?')}`\n"
        f"Hacim Profili: `{coin.get('volume_profile', '?')}`\n"
        f"BTC Korelasyon: `{(coin.get('btc_correlation') or 0):.2f}` (`{coin.get('btc_correlation_group') or '?'}`)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    # Current signals
    for tf in ["4h", "1d"]:
        candles_raw = db.get_candles(symbol, tf, 250)
        if not candles_raw:
            continue
        candles = [dict(c) for c in reversed(candles_raw)]
        signals = detect_signals(candles)
        snapshot = get_indicator_snapshot(candles)

        text += f"\n*{tf} gostergeler:*\n"
        if snapshot.get("ema_cross"):
            text += f"  EMA 20/50: `{snapshot['ema_cross']}`\n"
        if snapshot.get("bb_squeeze") is not None:
            text += f"  BB Sikisma: `{'Evet' if snapshot['bb_squeeze'] else 'Hayir'}`\n"
        if snapshot.get("volume_ratio"):
            text += f"  Hacim Orani: `{snapshot['volume_ratio']}x`\n"

        if signals:
            text += f"  Aktif sinyaller: `{', '.join(signals.keys())}`\n"

    # Scores for this coin's dimensions
    text += f"\n*Yontem skorlari (rejim: {r['btc_trend']}):*\n"
    all_scores = db.get_scores(dimension="btc_trend", dimension_value=r["btc_trend"])
    method_scores = {}
    for s in all_scores:
        if s["method_name"] not in method_scores:
            method_scores[s["method_name"]] = s

    for method_name, s in sorted(method_scores.items(), key=lambda x: x[1]["win_rate_7d"], reverse=True):
        icon = "✅" if s["win_rate_7d"] >= 60 else ("⚠️" if s["win_rate_7d"] >= 45 else "❌")
        text += f"  {icon} `{method_name:15s}` %{s['win_rate_7d']:.0f} basari (ort: %{s['avg_return_7d']:+.1f})\n"

    # Composite score + pump probability
    candles_4h = db.get_candles(symbol, "4h", 250)
    if candles_4h:
        candles_list = [dict(c) for c in reversed(candles_4h)]
        signals = detect_signals(candles_list)
        active_methods = [m for m in signals.keys() if m in method_scores]
        if active_methods:
            composite = sum(method_scores[m]["win_rate_7d"] for m in active_methods) / len(active_methods)
            text += f"\n*Toplam arastirma skoru: `{composite:.0f}/100`*\n"
            text += f"({len(active_methods)} yontem aktif: {', '.join(active_methods)})\n"

        # Pump probability from pump_condition_scores
        pump_probs = _get_pump_probabilities(signals.keys(), coin)
        if pump_probs:
            text += "\n*Pump olasiliklari:*\n"
            for cond, prob, total in pump_probs[:5]:
                icon = "🔥" if prob >= 40 else ("⚡" if prob >= 25 else "")
                text += f"  `{cond}`: %{prob:.1f} ({total} orneklem) {icon}\n"

    await safe_send(m.chat.id, text)


@dp.message(Command("yontem"))
async def cmd_method(m: types.Message):
    parts = m.text.strip().split()
    if len(parts) < 2:
        await m.answer("Kullanim: /yontem EMA\n\nYontemler: macd, ema, bb, hacim, birikim, multi, rsi, obv, stoch, whale")
        return

    method = parts[1].lower()
    method_name = METHOD_MAP.get(method, method)

    text = f"*{method_name} Performans Raporu*\n━━━━━━━━━━━━━━━━━━━━\n"

    # By regime
    text += "\n*Rejim bazli basari:*\n"
    for dim_val in ["yukselis", "dusus", "yatay"]:
        scores = db.get_scores(method_name=method_name, dimension="btc_trend", dimension_value=dim_val)
        if scores:
            s = scores[0]
            icon = {"yukselis": "📈", "dusus": "📉", "yatay": "➡️"}.get(dim_val, "")
            text += f"  {icon} BTC {dim_val}: %{s['win_rate_7d']:.0f} ({s['total_signals']} sinyal)\n"

    for dim_val in ["artiyor", "azaliyor", "sabit"]:
        scores = db.get_scores(method_name=method_name, dimension="dominance_trend", dimension_value=dim_val)
        if scores:
            s = scores[0]
            text += f"  Dom. {dim_val}: %{s['win_rate_7d']:.0f} ({s['total_signals']} sinyal)\n"

    # By timeframe
    text += "\n*Zaman dilimi bazli:*\n"
    for tf in TIMEFRAMES:
        scores = db.get_scores(method_name=method_name, timeframe=tf, dimension="overall", dimension_value="all")
        if scores:
            s = scores[0]
            text += f"  `{tf:4s}`: %{s['win_rate_7d']:.0f} basari — {s['total_signals']} sinyal (ort: %{s['avg_return_7d']:+.1f})\n"

    # By market cap
    text += "\n*Market cap bazli:*\n"
    for mcap in ["top50", "51-100", "101-200", "200+"]:
        scores = db.get_scores(method_name=method_name, dimension="mcap_group", dimension_value=mcap)
        if scores:
            s = scores[0]
            text += f"  `{mcap:8s}`: %{s['win_rate_7d']:.0f} ({s['total_signals']} sinyal)\n"

    # By sector
    text += "\n*Sektor bazli:*\n"
    for sector in ["L1", "L2", "DeFi", "AI", "Meme", "Gaming"]:
        scores = db.get_scores(method_name=method_name, dimension="sector", dimension_value=sector)
        if scores:
            s = scores[0]
            text += f"  `{sector:8s}`: %{s['win_rate_7d']:.0f} ({s['total_signals']} sinyal)\n"

    await safe_send(m.chat.id, text)


@dp.message(Command("top"))
async def cmd_top(m: types.Message):
    r = get_current_regime()
    top = db.get_top_scored_coins(r, limit=10)
    if not top:
        await m.answer("Henuz yeterli veri yok. Backtest tamamlanmasi bekleniyor.")
        return

    text = f"*Bu Rejimde En Yuksek Skorlu Coinler*\n"
    text += f"(BTC: {r['btc_trend']} | Dom: {r['dominance_trend']})\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"

    for i, tc in enumerate(top, 1):
        text += f"`{i:2d}.` `{tc['symbol']:10s}` | {tc['method_name']} ({tc['timeframe']}) | %{tc['win_rate_7d']:.0f} basari\n"

    text += f"\nDetay icin: /coin [isim]"
    await safe_send(m.chat.id, text)


@dp.message(Command("top50"))
async def cmd_top50(m: types.Message):
    scores = db.get_scores(dimension="mcap_group", dimension_value="top50")
    if not scores:
        await m.answer("Top 50 icin henuz skor yok.")
        return

    text = "*Top 50 Market Cap — Yontem Performanslari*\n━━━━━━━━━━━━━━━━━━━━\n"
    seen = set()
    for s in scores[:10]:
        key = f"{s['method_name']}_{s['timeframe']}"
        if key in seen:
            continue
        seen.add(key)
        text += f"`{s['method_name']:15s}` {s['timeframe']} | %{s['win_rate_7d']:.0f} basari | ort: %{s['avg_return_7d']:+.1f}\n"

    await safe_send(m.chat.id, text)


@dp.message(Command("sektor"))
async def cmd_sector(m: types.Message):
    parts = m.text.strip().split()
    if len(parts) < 2:
        await m.answer("Kullanim: /sektor DeFi\n\nSektorler: L1, L2, DeFi, AI, Meme, Gaming, Altyapi")
        return

    sector = parts[1]
    scores = db.get_scores(dimension="sector", dimension_value=sector)
    if not scores:
        await m.answer(f"`{sector}` sektoru icin henuz skor yok.")
        return

    text = f"*{sector} Sektoru — Yontem Performanslari*\n━━━━━━━━━━━━━━━━━━━━\n"
    seen = set()
    for s in scores[:10]:
        key = f"{s['method_name']}_{s['timeframe']}"
        if key in seen:
            continue
        seen.add(key)
        text += f"`{s['method_name']:15s}` {s['timeframe']} | %{s['win_rate_7d']:.0f} basari | {s['total_signals']} sinyal\n"

    await safe_send(m.chat.id, text)


@dp.message(Command("karsilastir"))
async def cmd_compare(m: types.Message):
    parts = m.text.strip().split()
    if len(parts) < 3:
        await m.answer("Kullanim: /karsilastir MACD EMA")
        return

    m1 = METHOD_MAP.get(parts[1].lower(), parts[1].lower())
    m2 = METHOD_MAP.get(parts[2].lower(), parts[2].lower())

    text = f"*{m1} vs {m2} Karsilastirma*\n━━━━━━━━━━━━━━━━━━━━\n"

    for dim, dim_label in [("btc_trend", "Rejim"), ("mcap_group", "Market Cap"), ("sector", "Sektor")]:
        text += f"\n*{dim_label} bazli:*\n"
        s1_all = db.get_scores(method_name=m1, dimension=dim)
        s2_all = db.get_scores(method_name=m2, dimension=dim)

        s1_map = {s["dimension_value"]: s for s in s1_all}
        s2_map = {s["dimension_value"]: s for s in s2_all}

        all_vals = set(list(s1_map.keys()) + list(s2_map.keys()))
        for val in sorted(all_vals):
            r1 = s1_map.get(val)
            r2 = s2_map.get(val)
            wr1 = f"%{r1['win_rate_7d']:.0f}" if r1 else "N/A"
            wr2 = f"%{r2['win_rate_7d']:.0f}" if r2 else "N/A"
            winner = ""
            if r1 and r2:
                if r1["win_rate_7d"] > r2["win_rate_7d"]:
                    winner = " ◀"
                elif r2["win_rate_7d"] > r1["win_rate_7d"]:
                    winner = " ▶"
            text += f"  `{val:12s}` {wr1:>5s}{winner if winner == ' ◀' else ''} | {wr2:>5s}{winner if winner == ' ▶' else ''}\n"

    await safe_send(m.chat.id, text)


def _get_pump_probabilities(active_conditions, coin):
    conn = db.get_conn()
    results = []
    mcap = coin.get("mcap_group", "all")
    sector = coin.get("sector", "all")
    for cond in active_conditions:
        if cond == "multi_signal":
            continue
        for dim, dim_val in [("mcap_group", mcap), ("sector", sector), ("overall", "all")]:
            row = conn.execute(
                "SELECT pump_probability, total_occurrences FROM pump_condition_scores "
                "WHERE condition=? AND dimension=? AND dimension_value=? "
                "ORDER BY pump_probability DESC LIMIT 1",
                (cond, dim, dim_val)
            ).fetchone()
            if row and row["total_occurrences"] >= 10:
                label = f"{cond}" if dim == "overall" else f"{cond} ({dim_val})"
                results.append((label, row["pump_probability"], row["total_occurrences"]))
                break
    results.sort(key=lambda x: x[1], reverse=True)
    return results


async def check_and_notify_signals():
    conn = db.get_conn()
    coins = db.get_all_coins()
    r = get_current_regime()

    for coin in coins[:100]:
        coin = dict(coin)
        symbol = coin["symbol"]
        for tf in ["1h", "4h"]:
            candles_raw = db.get_candles(symbol, tf, 250)
            if not candles_raw or len(candles_raw) < 60:
                continue
            candles = [dict(c) for c in reversed(candles_raw)]
            signals = detect_signals(candles)

            bullish = [k for k, v in signals.items()
                       if v["type"] in ("bullish_cross", "golden_cross", "squeeze",
                                        "spike", "accumulation", "large_trades",
                                        "bullish_divergence", "oversold_exit")]
            if len(bullish) < 3:
                continue

            pump_probs = _get_pump_probabilities(signals.keys(), coin)
            top_prob = pump_probs[0][1] if pump_probs else 0

            base = symbol.replace("USDT", "")
            text = (
                f"🔔 *Yeni Sinyal: {base}*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Timeframe: {tf}\n\n"
                f"*Aktif kosullar:*\n"
            )
            for k in bullish:
                val = signals[k].get("value", "")
                text += f"  ✅ {k} ({val})\n"

            if pump_probs:
                text += "\n*Pump olasiliklari:*\n"
                for cond, prob, total in pump_probs[:3]:
                    icon = "🔥" if prob >= 40 else ""
                    text += f"  {cond}: `%{prob:.1f}` {icon}\n"

            scores = db.get_scores(dimension="btc_trend", dimension_value=r["btc_trend"])
            method_win = {s["method_name"]: s for s in scores}
            active_with_scores = [m for m in bullish if m in method_win]
            if active_with_scores:
                text += f"\n*Gecmis basari (rejim: {r['btc_trend']}):*\n"
                for m in active_with_scores[:3]:
                    s = method_win[m]
                    text += f"  {m}: %{s['win_rate_7d']:.0f} win ({s['total_signals']} sinyal)\n"

            composite = 0
            if active_with_scores:
                composite = sum(method_win[m]["win_rate_7d"] for m in active_with_scores) / len(active_with_scores)
            text += f"\nSkor: `{composite:.0f}/100` | MCap: {coin.get('mcap_group','?')} | Sektor: {coin.get('sector','?')}\n"
            text += f"/coin {base} ile detay"

            await broadcast(text)
            await asyncio.sleep(0.5)


async def check_and_notify_pumps():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM pumps WHERE pump_time > datetime('now', '-2 hours') "
        "ORDER BY pump_pct DESC LIMIT 5"
    ).fetchall()

    for pump in rows:
        pump = dict(pump)
        already = conn.execute(
            "SELECT 1 FROM pump_notifications WHERE symbol=? AND pump_time=?",
            (pump["symbol"], pump["pump_time"])
        ).fetchone()
        if already:
            continue

        base = pump["symbol"].replace("USDT", "")
        text = (
            f"🚀 *PUMP TESPIT: {base} +{pump['pump_pct']:.0f}%*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Timeframe: {pump['timeframe']}\n\n"
            f"*Pump oncesi aktif kosullar:*\n"
        )
        if pump.get("pre_bb_squeeze"):
            text += "  ✅ BB Sikisma\n"
        if pump.get("pre_volume_ratio") and pump["pre_volume_ratio"] >= 2:
            text += f"  ✅ Volume Spike ({pump['pre_volume_ratio']:.1f}x)\n"
        if pump.get("pre_accumulation"):
            text += "  ✅ Accumulation\n"

        text += f"\n/coin {base} ile detay"
        await broadcast(text)

        try:
            conn.execute(
                "INSERT OR IGNORE INTO pump_notifications (symbol, pump_time) VALUES (?, ?)",
                (pump["symbol"], pump["pump_time"])
            )
            conn.commit()
        except Exception:
            pass


async def check_and_notify_regime_change():
    global _last_regime
    r = get_current_regime()
    changed = False

    if _last_regime["btc_trend"] and r["btc_trend"] != _last_regime["btc_trend"]:
        changed = True
    if _last_regime["dominance_trend"] and r["dominance_trend"] != _last_regime["dominance_trend"]:
        changed = True

    old_trend = _last_regime["btc_trend"]
    _last_regime["btc_trend"] = r["btc_trend"]
    _last_regime["dominance_trend"] = r["dominance_trend"]

    if not changed:
        return

    text = (
        f"⚠️ *Rejim Degisikligi*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"BTC Trend: `{old_trend}` → `{r['btc_trend']}`\n"
        f"BTC: `${r.get('btc_price', 0):,.0f}`\n"
        f"Korku/Acgozluluk: `{r.get('fear_greed_value', 50)}` — `{r.get('fear_greed_label', 'notr')}`\n\n"
    )

    scores = db.get_scores(dimension="btc_trend", dimension_value=r["btc_trend"])
    if scores:
        text += "*Bu rejimde en iyi yontemler:*\n"
        seen = set()
        for s in scores[:5]:
            if s["method_name"] in seen:
                continue
            seen.add(s["method_name"])
            text += f"  {s['method_name']}: %{s['win_rate_7d']:.0f}\n"

    await broadcast(text)


def build_daily_report():
    r = get_current_regime()
    trend_icon = {"yukselis": "📈", "dusus": "📉", "yatay": "➡️"}.get(r["btc_trend"], "➡️")

    text = (
        f"*Gunluk Piyasa Raporu*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"BTC: `${r.get('btc_price', 0):,.0f}` {trend_icon} `{r['btc_trend']}`\n"
        f"Dominance: `%{r.get('btc_dominance', 0):.1f}` (`{r['dominance_trend']}`)\n"
        f"Korku/Acgozluluk: `{r.get('fear_greed_value', 50)}` — `{r.get('fear_greed_label', 'notr')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    scores = db.get_scores(dimension="btc_trend", dimension_value=r["btc_trend"])
    if scores:
        text += "\n*Bu rejimde en basarili yontemler:*\n"
        seen = set()
        count = 0
        for s in scores:
            key = f"{s['method_name']}_{s['timeframe']}"
            if key in seen:
                continue
            seen.add(key)
            bar = "█" * int(s["win_rate_7d"] / 10) + "░" * (10 - int(s["win_rate_7d"] / 10))
            text += f"`{s['method_name']:15s}` {s['timeframe']:3s} |{bar}| %{s['win_rate_7d']:.0f}\n"
            count += 1
            if count >= 5:
                break

    top = db.get_top_scored_coins(r, limit=5)
    if top:
        text += "\n*One cikan coinler:*\n"
        for i, tc in enumerate(top, 1):
            text += f"`{i}.` `{tc['symbol']}` — {tc['method_name']} (%{tc['win_rate_7d']:.0f})\n"

    text += "\nDetay icin: /coin [isim] veya /yontem [isim]"
    return text


@dp.message(Command("whale"))
async def cmd_whale(m: types.Message):
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) as cnt FROM whale_alerts").fetchone()["cnt"]
    rows = conn.execute(
        "SELECT * FROM whale_alerts ORDER BY detected_time DESC LIMIT 10"
    ).fetchall()

    text = f"*Whale / Buyuk Islem Tespitleri*\n━━━━━━━━━━━━━━━━━━━━\nToplam: `{total}` tespit\n\n"

    if not rows:
        text += "Henuz whale tespiti yok."
    else:
        for r in rows:
            r = dict(r)
            ret = r.get("pct_change_24h")
            ret_str = f"{ret:+.1f}%" if ret is not None else "—"
            text += f"🐋 `{r['symbol']:10s}` | `{r['ratio']:.1f}x` buyuk | 24s: `{ret_str}`\n"

    text += "\n_Ort. islem buyuklugu 30 gunluk ortalamanin 5x+ ustu_"
    await safe_send(m.chat.id, text)


@dp.message(Command("korelasyon"))
async def cmd_correlation(m: types.Message):
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) as cnt FROM correlation_breaks").fetchone()["cnt"]
    rows = conn.execute(
        "SELECT * FROM correlation_breaks ORDER BY detected_time DESC LIMIT 10"
    ).fetchall()

    text = f"*Korelasyon Kirilmalari*\n━━━━━━━━━━━━━━━━━━━━\nToplam: `{total}` kirilma\n\n"

    if not rows:
        text += "Henuz korelasyon kirilmasi tespit edilmedi."
    else:
        for r in rows:
            r = dict(r)
            ret = r.get("pct_change_7d")
            ret_str = f"{ret:+.1f}%" if ret is not None else "—"
            text += f"🔗 `{r['symbol']:10s}` | 30g: `{r['corr_30d']:.2f}` → 48s: `{r['corr_48h']:.2f}` | 7g: `{ret_str}`\n"

    text += "\n_BTC ile yuksek korelasyonlu coinlerin aniden bagimsiz hareket ettigi anlar_"
    await safe_send(m.chat.id, text)


@dp.message(Command("lider"))
async def cmd_leader(m: types.Message):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT sector, leader_symbol, "
        "AVG(follower_delay_hours) as avg_delay, "
        "COUNT(*) as cnt "
        "FROM sector_leaders "
        "GROUP BY sector "
        "ORDER BY avg_delay"
    ).fetchall()

    text = "*Sektor Lider-Takipci Analizi*\n━━━━━━━━━━━━━━━━━━━━\n\n"

    if not rows:
        text += "Henuz lider-takipci verisi yok."
    else:
        for r in rows:
            r = dict(r)
            text += (
                f"*{r['sector']}* — Lider: `{r['leader_symbol'].replace('USDT','')}`\n"
                f"  Ort. gecikme: `{r['avg_delay']:.1f} saat` | `{r['cnt']}` pattern\n\n"
            )

    text += "_Lider coin %5+ hareket ettiginde takipcilerin tepki suresi_"
    await safe_send(m.chat.id, text)

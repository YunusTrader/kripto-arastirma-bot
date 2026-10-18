import aiohttp
import asyncio
import time
import logging
from config import (
    BINANCE_BASE, COINGECKO_BASE, COINGECKO_KEY, FEAR_GREED_URL,
    TIMEFRAMES, KLINE_LIMITS, SECTORS
)
import database as db

log = logging.getLogger(__name__)

CG_HEADERS = {"x-cg-demo-api-key": COINGECKO_KEY} if COINGECKO_KEY else None


async def fetch_json(session, url, params=None, headers=None, retries=3):
    attempt = 0
    rate_limit_count = 0
    while attempt < retries:
        try:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 429:
                    rate_limit_count += 1
                    if rate_limit_count > 5:
                        log.warning(f"Too many rate limits for {url}, giving up")
                        return None
                    try:
                        wait = min(int(resp.headers.get("Retry-After", 5)), 60)
                    except (ValueError, TypeError):
                        wait = 5
                    log.warning(f"Rate limited, waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                if resp.status == 200:
                    return await resp.json()
                if resp.status in (400, 404):
                    return None
                log.warning(f"HTTP {resp.status} for {url}")
        except Exception as e:
            log.warning(f"Fetch error ({attempt+1}/{retries}): {e}")
        await asyncio.sleep(2 ** attempt)
        attempt += 1
    return None


async def get_all_usdt_symbols(session):
    data = await fetch_json(session, f"{BINANCE_BASE}/api/v3/exchangeInfo")
    if not data:
        return []
    symbols = []
    for s in data.get("symbols", []):
        if (s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
                and s["isSpotTradingAllowed"]):
            symbols.append({
                "symbol": s["symbol"],
                "base": s["baseAsset"]
            })
    return symbols


async def fetch_klines(session, symbol, interval, limit=500):
    data = await fetch_json(
        session,
        f"{BINANCE_BASE}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit}
    )
    return data or []


async def collect_candles(session, symbols, timeframe, limit=None):
    if limit is None:
        limit = KLINE_LIMITS.get(timeframe, 500)
    batch_size = 5
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        tasks = [fetch_klines(session, s, timeframe, limit) for s in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for sym, result in zip(batch, results):
            if isinstance(result, list) and result:
                db.save_candles(sym, timeframe, result)
        await asyncio.sleep(2)
    log.info(f"Collected {timeframe} candles for {len(symbols)} symbols")


async def fetch_coingecko_market_data(session, page=1, per_page=250):
    data = await fetch_json(
        session,
        f"{COINGECKO_BASE}/coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": per_page,
            "page": page,
            "sparkline": "false"
        },
        headers=CG_HEADERS
    )
    return data or []


async def collect_coingecko_rankings(session):
    all_coins = []
    for page in range(1, 4):
        data = await fetch_coingecko_market_data(session, page=page)
        all_coins.extend(data)
        await asyncio.sleep(1.5)

    symbol_map = {}
    for i, coin in enumerate(all_coins, 1):
        sym = coin.get("symbol", "").upper()
        if sym not in symbol_map:
            symbol_map[sym] = {
                "rank": coin.get("market_cap_rank") or i,
                "market_cap": coin.get("market_cap") or 0,
            }
    return symbol_map


def determine_mcap_group(rank):
    if rank <= 50:
        return "top50"
    elif rank <= 100:
        return "51-100"
    elif rank <= 200:
        return "101-200"
    return "200+"


def determine_sector(base_asset):
    for sector, coins in SECTORS.items():
        if base_asset in coins:
            return sector
    return "Diger"


async def fetch_btc_dominance(session):
    data = await fetch_json(session, f"{COINGECKO_BASE}/global", headers=CG_HEADERS)
    if data and "data" in data:
        return data["data"].get("market_cap_percentage", {}).get("btc", 0)
    return 0


async def fetch_total_market_volume(session):
    data = await fetch_json(session, f"{COINGECKO_BASE}/global", headers=CG_HEADERS)
    if data and "data" in data:
        return data["data"].get("total_volume", {}).get("usd", 0)
    return 0


async def fetch_fear_greed(session):
    data = await fetch_json(session, FEAR_GREED_URL)
    if data and "data" in data and data["data"]:
        entry = data["data"][0]
        return {
            "value": int(entry.get("value", 50)),
            "label": entry.get("value_classification", "Neutral")
        }
    return {"value": 50, "label": "Neutral"}


async def fetch_btc_price(session):
    data = await fetch_json(
        session,
        f"{BINANCE_BASE}/api/v3/ticker/price",
        params={"symbol": "BTCUSDT"}
    )
    if data:
        return float(data.get("price", 0))
    return 0


async def initial_data_load(session):
    log.info("Starting initial data load...")

    symbols_info = await get_all_usdt_symbols(session)
    symbols = [s["symbol"] for s in symbols_info]
    log.info(f"Found {len(symbols)} USDT pairs")

    log.info("Saving coins to DB...")
    conn = db.get_conn()
    for s in symbols_info:
        existing = conn.execute("SELECT 1 FROM coins WHERE symbol=?", (s["symbol"],)).fetchone()
        if not existing:
            conn.execute("INSERT INTO coins (symbol, base_asset) VALUES (?,?)", (s["symbol"], s["base"]))
    conn.commit()
    log.info(f"Saved {len(symbols_info)} coins")

    log.info("Fetching CoinGecko rankings...")
    cg_rankings = await collect_coingecko_rankings(session)
    log.info(f"Got rankings for {len(cg_rankings)} coins")

    if not cg_rankings:
        log.warning("CoinGecko returned empty rankings, skipping classification")
        cg_rankings = {}

    for s in symbols_info:
        base = s["base"]
        if base in cg_rankings:
            rank = cg_rankings[base]["rank"]
            conn.execute(
                "UPDATE coins SET mcap_rank=?, mcap_group=?, sector=? WHERE symbol=?",
                (rank, determine_mcap_group(rank), determine_sector(base), s["symbol"])
            )
        else:
            conn.execute(
                "UPDATE coins SET mcap_group=?, sector=? WHERE symbol=?",
                ("200+", determine_sector(base), s["symbol"])
            )
    conn.commit()
    log.info("Coin classifications saved")

    candle_count = conn.execute("SELECT COUNT(*) as cnt FROM candles").fetchone()["cnt"]

    if candle_count > 10000:
        log.info(f"Found {candle_count} existing candles, doing incremental update only")
        for tf in TIMEFRAMES:
            limit = KLINE_LIMITS.get(tf, 500)
            update_limit = min(50, limit)
            log.info(f"Updating {tf} candles (last {update_limit})...")
            await collect_candles(session, symbols, tf, limit=update_limit)
            await asyncio.sleep(1)
    else:
        log.info("No existing data, doing full initial load")
        # Priority: load top 100 coins first for faster usability
        ranked_symbols = []
        rest_symbols = []
        for s in symbols:
            base = s.replace("USDT", "")
            if base in cg_rankings and cg_rankings[base]["rank"] <= 100:
                ranked_symbols.append(s)
            else:
                rest_symbols.append(s)
        log.info(f"Priority load: {len(ranked_symbols)} top coins first, then {len(rest_symbols)} rest")

        for tf in TIMEFRAMES:
            log.info(f"Collecting {tf} candles (top coins)...")
            await collect_candles(session, ranked_symbols, tf)
            await asyncio.sleep(1)
        log.info("Top coins loaded — bot is now usable")

        for tf in TIMEFRAMES:
            log.info(f"Collecting {tf} candles (remaining coins)...")
            await collect_candles(session, rest_symbols, tf)
            await asyncio.sleep(1)

    log.info("Initial data load complete")
    return symbols


async def update_candles(session, symbols, timeframe, limit=50):
    await collect_candles(session, symbols, timeframe, limit)


async def update_coingecko(session):
    cg_rankings = await collect_coingecko_rankings(session)
    coins = db.get_all_coins()
    for coin in coins:
        base = coin["base_asset"]
        if base in cg_rankings:
            rank = cg_rankings[base]["rank"]
            db.save_coin(
                coin["symbol"], base,
                mcap_rank=rank,
                mcap_group=determine_mcap_group(rank)
            )

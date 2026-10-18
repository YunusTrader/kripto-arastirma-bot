import asyncio
import threading
import logging
import time
import aiohttp
from flask import Flask, send_from_directory
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import FLASK_PORT, DATA_UPDATE_INTERVALS, DAILY_REPORT_HOUR, WEEKLY_REPORT_DAY
import database as db
from data_collector import (
    initial_data_load, update_candles, update_coingecko,
    get_all_usdt_symbols
)
from coin_classifier import classify_all_coins
from market_regime import update_regime
from backtester import run_full_backtest
from advanced_analytics import run_all_advanced_analytics
from telegram_bot import dp, bot, broadcast, build_daily_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)

# Flask keep-alive + dashboard
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app = Flask("", static_folder=STATIC_DIR)

from dashboard import dashboard_bp
app.register_blueprint(dashboard_bp)

@app.route("/")
def home():
    return send_from_directory(STATIC_DIR, "index.html")

def run_flask():
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False)


# Global state
symbols_list = []
session = None


async def scheduled_update_candles_1h():
    if session and symbols_list:
        await update_candles(session, symbols_list, "1h", limit=10)
        db.sync_db()

async def scheduled_update_candles_4h():
    if session and symbols_list:
        await update_candles(session, symbols_list, "4h", limit=5)
        db.sync_db()

async def scheduled_update_candles_1d():
    if session and symbols_list:
        await update_candles(session, symbols_list, "1d", limit=3)
        db.sync_db()

async def scheduled_update_coingecko():
    if session:
        await update_coingecko(session)

async def scheduled_update_regime():
    if session:
        await update_regime(session)

async def scheduled_classify():
    await asyncio.get_event_loop().run_in_executor(None, classify_all_coins)

async def scheduled_backtest():
    await asyncio.get_event_loop().run_in_executor(None, run_full_backtest)

async def scheduled_advanced():
    await asyncio.get_event_loop().run_in_executor(None, run_all_advanced_analytics)

async def scheduled_daily_report():
    text = build_daily_report()
    await broadcast(text)

async def scheduled_weekly_report():
    text = "*Haftalik Yontem Performans Raporu*\n━━━━━━━━━━━━━━━━━━━━\n"
    scores = db.get_scores(dimension="overall", dimension_value="all")
    if scores:
        seen = set()
        for s in scores[:15]:
            key = f"{s['method_name']}_{s['timeframe']}"
            if key in seen:
                continue
            seen.add(key)
            text += (
                f"`{s['method_name']:15s}` {s['timeframe']:3s} | "
                f"7g: %{(s['win_rate_7d'] or 0):.0f} | "
                f"ort: %{(s['avg_return_7d'] or 0):+.1f} | "
                f"{s['total_signals'] or 0} sinyal\n"
            )
    await broadcast(text)


def setup_scheduler():
    scheduler = AsyncIOScheduler()

    scheduler.add_job(scheduled_update_candles_1h, "interval",
                      seconds=DATA_UPDATE_INTERVALS["candles_1h"], id="candles_1h")
    scheduler.add_job(scheduled_update_candles_4h, "interval",
                      seconds=DATA_UPDATE_INTERVALS["candles_4h"], id="candles_4h")
    scheduler.add_job(scheduled_update_candles_1d, "interval",
                      seconds=DATA_UPDATE_INTERVALS["candles_1d"], id="candles_1d")
    scheduler.add_job(scheduled_update_coingecko, "interval",
                      seconds=DATA_UPDATE_INTERVALS["coingecko"], id="coingecko")
    scheduler.add_job(scheduled_update_regime, "interval",
                      seconds=DATA_UPDATE_INTERVALS["regime"], id="regime")
    scheduler.add_job(scheduled_classify, "interval",
                      seconds=DATA_UPDATE_INTERVALS["classify"], id="classify")
    scheduler.add_job(scheduled_backtest, "interval",
                      seconds=DATA_UPDATE_INTERVALS["backtest"], id="backtest")
    scheduler.add_job(scheduled_advanced, "interval",
                      seconds=DATA_UPDATE_INTERVALS.get("advanced", 43200), id="advanced")

    scheduler.add_job(scheduled_daily_report, "cron",
                      hour=DAILY_REPORT_HOUR, minute=0, id="daily_report")
    scheduler.add_job(scheduled_weekly_report, "cron",
                      day_of_week=WEEKLY_REPORT_DAY, hour=DAILY_REPORT_HOUR, minute=30, id="weekly_report")

    scheduler.start()
    return scheduler


async def background_init(sess):
    global symbols_list, session
    session = sess

    log.info("Starting initial data load (this may take several minutes)...")
    try:
        symbols_list = await initial_data_load(sess)
        log.info(f"Loaded {len(symbols_list)} symbols")
    except Exception as e:
        log.error(f"Initial load error: {e}")
        syms = await get_all_usdt_symbols(sess)
        symbols_list = [s["symbol"] for s in syms]

    loop = asyncio.get_event_loop()

    log.info("Classifying coins...")
    try:
        await loop.run_in_executor(None, classify_all_coins)
    except Exception as e:
        log.error(f"Classification error: {e}")

    log.info("Updating market regime...")
    try:
        await update_regime(sess)
    except Exception as e:
        log.error(f"Regime error: {e}")

    log.info("Clearing old backtest data for fresh run...")
    try:
        conn = db.get_conn()
        conn.execute("DELETE FROM method_signals")
        conn.execute("DELETE FROM method_scores")
        conn.execute("DELETE FROM pumps")
        conn.commit()
        log.info("Old backtest data cleared")
    except Exception as e:
        log.error(f"Clear error: {e}")

    log.info("Running initial backtest...")
    try:
        await loop.run_in_executor(None, run_full_backtest)
    except Exception as e:
        log.error(f"Backtest error: {e}")

    log.info("Running advanced analytics...")
    try:
        await loop.run_in_executor(None, run_all_advanced_analytics)
    except Exception as e:
        log.error(f"Advanced analytics error: {e}")

    log.info("Starting scheduler...")
    setup_scheduler()

    db.sync_db()
    log.info("Database synced to Turso")

    await broadcast("Veri yukleme ve backtest tamamlandi!\n\n/rapor komutu ile baslayabilirsiniz.")
    log.info("Background init complete")


async def main():
    global symbols_list, session

    db.init_db()
    log.info("Database initialized")

    async with aiohttp.ClientSession() as sess:
        session = sess

        await broadcast("Bot basladi! Veri yukleniyor, bu 15-20 dk surebilir...\n\nYukleme bitince ayrica haber verecegim.")
        log.info("Telegram bot starting, data load will run in background...")

        init_task = asyncio.create_task(background_init(sess))
        init_task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)

        try:
            await dp.start_polling(bot)
        except Exception as e:
            log.error(f"Polling error: {e}")


if __name__ == "__main__":
    try:
        threading.Thread(target=run_flask, daemon=True).start()
    except Exception as e:
        log.error(f"Flask error: {e}")

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot kapatildi.")
    except Exception as e:
        log.error(f"Fatal error: {e}")

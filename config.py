import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MY_CHAT_ID = int(os.getenv("MY_CHAT_ID", "0"))
FLASK_PORT = int(os.getenv("PORT", 10000))

TURSO_DB_URL = os.getenv("TURSO_DB_URL", "")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
COINGECKO_KEY = os.getenv("COINGECKO_KEY", "")

BINANCE_BASE = "https://api.binance.com"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
FEAR_GREED_URL = "https://api.alternative.me/fng/"

TIMEFRAMES = ["1h", "4h", "1d", "1w"]
TIMEFRAME_MINUTES = {"1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
KLINE_LIMITS = {"1h": 500, "4h": 500, "1d": 365, "1w": 52}

MCAP_GROUPS = {
    "top50": (1, 50),
    "51-100": (51, 100),
    "101-200": (101, 200),
    "200+": (201, 9999),
}

SECTORS = {
    "L1": ["BTC", "ETH", "SOL", "ADA", "AVAX", "DOT", "ATOM", "NEAR", "APT", "SUI", "SEI", "TON"],
    "L2": ["MATIC", "ARB", "OP", "IMX", "MANTA", "STRK", "ZK", "METIS"],
    "DeFi": ["UNI", "AAVE", "MKR", "CRV", "COMP", "SNX", "DYDX", "SUSHI", "1INCH", "PENDLE", "JUP"],
    "AI": ["FET", "RENDER", "AGIX", "OCEAN", "TAO", "WLD", "ARKM", "AKT"],
    "Meme": ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME", "TURBO"],
    "Gaming": ["AXS", "SAND", "MANA", "GALA", "IMX", "ILV", "RONIN", "PIXEL"],
    "Altyapi": ["LINK", "GRT", "FIL", "AR", "RNDR", "THETA", "ROSE", "PYTH"],
}

PUMP_THRESHOLD_PCT = 10.0
PUMP_LOOKBACK_HOURS = [1, 4, 12, 24]
BACKTEST_MONTHS = 6

RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
BB_SQUEEZE_THRESHOLD = 0.02
VOLUME_SPIKE_MULTIPLIER = 3.0
ACCUMULATION_VOL_MIN = 1.5
ACCUMULATION_VOL_MAX = 2.5
ACCUMULATION_PRICE_MAX_CHANGE = 1.0

SCORE_MIN_SAMPLES = 5

DAILY_REPORT_HOUR = 9
WEEKLY_REPORT_DAY = 0  # Monday

DATA_UPDATE_INTERVALS = {
    "candles_1h": 900,    # 15 min
    "candles_4h": 3600,   # 1 hour
    "candles_1d": 14400,  # 4 hours
    "candles_1w": 43200,  # 12 hours
    "coingecko": 3600,    # 1 hour
    "fear_greed": 3600,   # 1 hour
    "regime": 900,        # 15 min
    "classify": 86400,    # 24 hours
    "backtest": 86400,    # 24 hours
    "advanced": 43200,    # 12 hours
}

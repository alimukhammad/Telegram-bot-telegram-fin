"""Kraken public REST API client and pair-alias mapping."""
from __future__ import annotations

import logging
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"
KRAKEN_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"

# ---------------------------------------------------------------------------
# Alias → Kraken pair name mapping
# Kraken uses XBT instead of BTC and prefixes some currencies with X/Z.
# The keys are upper-cased user-friendly aliases; values are Kraken pair names
# as returned by the Ticker endpoint.
# ---------------------------------------------------------------------------
_ALIAS_MAP: Dict[str, str] = {
    # Bitcoin
    "BTCUSD": "XXBTZUSD",
    "BTCUSDT": "XBTUSDT",
    "BTCEUR": "XXBTZEUR",
    "BTCGBP": "XXBTZGBP",
    "XBTUSD": "XXBTZUSD",
    "XBTUSDT": "XBTUSDT",
    "XBTEUR": "XXBTZEUR",
    # Ethereum
    "ETHUSD": "XETHZUSD",
    "ETHUSDT": "ETHUSDT",
    "ETHEUR": "XETHZEUR",
    "ETHBTC": "XETHXXBT",
    "ETHXBT": "XETHXXBT",
    # Solana
    "SOLUSD": "SOLUSD",
    "SOLUSDT": "SOLUSDT",
    "SOLEUR": "SOLEUR",
    # XRP
    "XRPUSD": "XXRPZUSD",
    "XRPUSDT": "XRPUSDT",
    "XRPEUR": "XXRPZEUR",
    # Litecoin
    "LTCUSD": "XLTCZUSD",
    "LTCUSDT": "LTCUSDT",
    # Cardano
    "ADAUSD": "ADAUSD",
    "ADAUSDT": "ADAUSDT",
    # Dogecoin
    "DOGEUSD": "XDGUSD",
    "DOGEUSDT": "DOGEUSDT",
    # Polkadot
    "DOTUSD": "DOTUSD",
    "DOTUSDT": "DOTUSDT",
    # Chainlink
    "LINKUSD": "LINKUSD",
    "LINKUSDT": "LINKUSDT",
    # Avalanche
    "AVAXUSD": "AVAXUSD",
    "AVAXUSDT": "AVAXUSDT",
    # Matic / Polygon
    "MATICUSD": "MATICUSD",
    "MATICUSDT": "MATICUSDT",
    # Uniswap
    "UNIUSD": "UNIUSD",
    "UNIUSDT": "UNIUSDT",
    # Atom / Cosmos
    "ATOMUSD": "ATOMUSD",
    "ATOMUSDT": "ATOMUSDT",
    # Paxos Gold (gold-backed token, 1 PAXG = 1 troy oz gold)
    "PAXGUSD": "PAXGUSD",
    "PAXGUSDT": "PAXGUSDT",
    "GOLDUSD": "PAXGUSD",
}


def resolve_pair(user_input: str) -> str:
    """Return the canonical Kraken pair name for *user_input*.

    If the input is already a known Kraken pair it is returned as-is
    (upper-cased).  Otherwise the alias map is consulted.  If still not found
    the upper-cased input is returned so that the Ticker call can attempt it
    directly (Kraken accepts both the pair name and its wsname in some calls).
    """
    upper = user_input.upper().strip()
    return _ALIAS_MAP.get(upper, upper)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_DISPLAY_MAP: Dict[str, str] = {
    "XXBTZUSD": "BTC/USD",
    "XBTUSDT": "BTC/USDT",
    "XXBTZEUR": "BTC/EUR",
    "XXBTZGBP": "BTC/GBP",
    "XETHZUSD": "ETH/USD",
    "ETHUSDT": "ETH/USDT",
    "XETHZEUR": "ETH/EUR",
    "XETHXXBT": "ETH/BTC",
    "SOLUSD": "SOL/USD",
    "SOLUSDT": "SOL/USDT",
    "SOLEUR": "SOL/EUR",
    "XXRPZUSD": "XRP/USD",
    "XRPUSDT": "XRP/USDT",
    "XXRPZEUR": "XRP/EUR",
    "XLTCZUSD": "LTC/USD",
    "LTCUSDT": "LTC/USDT",
    "ADAUSD": "ADA/USD",
    "ADAUSDT": "ADA/USDT",
    "XDGUSD": "DOGE/USD",
    "DOGEUSDT": "DOGE/USDT",
    "DOTUSD": "DOT/USD",
    "DOTUSDT": "DOT/USDT",
    "LINKUSD": "LINK/USD",
    "LINKUSDT": "LINK/USDT",
    "AVAXUSD": "AVAX/USD",
    "AVAXUSDT": "AVAX/USDT",
    "MATICUSD": "MATIC/USD",
    "MATICUSDT": "MATIC/USDT",
    "UNIUSD": "UNI/USD",
    "UNIUSDT": "UNI/USDT",
    "ATOMUSD": "ATOM/USD",
    "ATOMUSDT": "ATOM/USDT",
    "PAXGUSD": "GOLD/USD",
    "PAXGUSDT": "GOLD/USDT",
}


def friendly_name(kraken_pair: str) -> str:
    """Return human-readable display name for a Kraken pair."""
    return _DISPLAY_MAP.get(kraken_pair, kraken_pair)


def fmt_price(price: float) -> str:
    """Format price with dollar sign and appropriate decimals."""
    if price >= 1:
        return f"${price:,.2f}"
    return f"${price:,.6f}"


def fmt_cooldown(seconds: int) -> str:
    """Format cooldown seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if seconds % 60 == 0:
        return f"{minutes} min"
    return f"{minutes}m {seconds % 60}s"


# ---------------------------------------------------------------------------
# Kraken API
# ---------------------------------------------------------------------------

async def fetch_prices(pairs: list[str]) -> Dict[str, float]:
    """Fetch last-trade prices for *pairs* from the Kraken Ticker endpoint.

    Returns a dict ``{kraken_pair: price}``.  Pairs that could not be fetched
    are silently omitted (errors are logged).
    """
    if not pairs:
        return {}

    pair_str = ",".join(pairs)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(KRAKEN_TICKER_URL, params={"pair": pair_str})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("Kraken Ticker request failed: %s", exc)
        return {}

    if data.get("error"):
        logger.error("Kraken API error: %s", data["error"])

    result: Dict[str, float] = {}
    for pair_name, ticker in (data.get("result") or {}).items():
        try:
            # "c" field is [last_trade_price, lot_volume]
            result[pair_name] = float(ticker["c"][0])
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Could not parse price for %s: %s", pair_name, exc)

    return result


async def validate_pair(kraken_pair: str) -> bool:
    """Return True if *kraken_pair* is a valid Kraken pair."""
    prices = await fetch_prices([kraken_pair])
    return bool(prices)

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

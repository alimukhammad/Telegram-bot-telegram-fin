"""Alert evaluation engine.

Evaluates all stored alert rules against current prices and dispatches
notifications via a caller-supplied async callback.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Dict

import storage

logger = logging.getLogger(__name__)

WINDOW_SECONDS: Dict[str, int] = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
}


def _compare(actual: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return actual > threshold
    if operator == "<":
        return actual < threshold
    if operator == ">=":
        return actual >= threshold
    if operator == "<=":
        return actual <= threshold
    return False


async def evaluate_alerts(
    prices: Dict[str, float],
    send_alert: Callable[[int, str], None],
) -> None:
    """Check every alert rule and fire *send_alert(user_id, message)* when triggered.

    *prices* maps Kraken pair name → current price.
    *send_alert* is an async callable.
    """
    alerts = storage.get_all_alerts()
    now = time.time()

    for alert in alerts:
        alert_id: int = alert["id"]
        user_id: int = alert["user_id"]
        pair: str = alert["pair"]
        alert_type: str = alert["alert_type"]
        operator: str = alert["operator"]
        value: float = alert["value"]
        window: str | None = alert["window"]
        cooldown: int = alert["cooldown"]
        last_triggered: float = alert["last_triggered"]

        current_price = prices.get(pair)
        if current_price is None:
            continue  # pair not in current price batch

        # Cooldown check
        if now - last_triggered < cooldown:
            continue

        triggered = False
        message = ""

        if alert_type == "price":
            triggered = _compare(current_price, operator, value)
            if triggered:
                message = (
                    f"🔔 *Price alert* — *{pair}*\n"
                    f"Current price: `{current_price:,.4f}`\n"
                    f"Condition: {operator} `{value:,.4f}`"
                )

        elif alert_type == "change":
            if window not in WINDOW_SECONDS:
                logger.warning("Unknown window %r for alert %d", window, alert_id)
                continue
            lookback = WINDOW_SECONDS[window]
            past_price = storage.get_price_at(pair, now - lookback)
            if past_price is None or past_price == 0:
                continue  # not enough history yet
            pct_change = (current_price - past_price) / past_price * 100.0
            triggered = _compare(pct_change, operator, value)
            if triggered:
                direction = "▲" if pct_change > 0 else "▼"
                message = (
                    f"📈 *Change alert* — *{pair}*\n"
                    f"Change over {window}: `{direction}{abs(pct_change):.2f}%`\n"
                    f"Condition: {operator} `{value:.2f}%`\n"
                    f"Price: `{current_price:,.4f}`"
                )

        if triggered:
            logger.info("Alert %d fired for user %d (%s)", alert_id, user_id, pair)
            storage.update_last_triggered(alert_id)
            await send_alert(user_id, message)

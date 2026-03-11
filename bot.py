"""Multi-user Telegram signals & alerts bot.

Commands
--------
/start                              – show help
/setpair <pair>                     – add pair to watchlist
/delpair <pair>                     – remove pair from watchlist
/pairs                              – list watchlist
/setalert <pair> price <op> <value> [cooldown=<s>]
/setalert <pair> change <op> <pct>% <window> [cooldown=<s>]
/alerts                             – list alerts
/delalert <id>                      – delete alert
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Coroutine
from typing import Any, Dict

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import alerts_engine
import config
import market_data
import storage

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "📊 *Kraken Signals & Alerts Bot*\n\n"
    "*Watchlist commands*\n"
    "  /setpair `<pair>` — add pair (e.g. BTCUSD)\n"
    "  /delpair `<pair>` — remove pair\n"
    "  /pairs — list your watchlist\n\n"
    "*Alert commands*\n"
    "  /setalert `<pair> price <op> <value> [cooldown=<s>]`\n"
    "    e.g. `/setalert BTCUSD price > 70000`\n"
    "    e.g. `/setalert BTCUSD price < 60000 cooldown=600`\n\n"
    "  /setalert `<pair> change <op> <pct>% <window> [cooldown=<s>]`\n"
    "    Windows: `5m` `15m` `1h`\n"
    "    e.g. `/setalert ETHUSD change > 2% 15m`\n\n"
    "  /alerts — list active alerts\n"
    "  /delalert `<id>` — delete alert by ID\n\n"
    "*Supported operators*: `>` `<` `>=` `<=`\n"
    "*Default cooldown*: 300 s (5 min)"
)

VALID_OPERATORS = {">", "<", ">=", "<="}
VALID_WINDOWS = {"5m", "15m", "1h"}


def _parse_cooldown(tokens: list[str], default: int = 300) -> int:
    for t in tokens:
        m = re.fullmatch(r"cooldown=(\d+)", t, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return default


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_setpair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text("Usage: /setpair <pair>  e.g. /setpair BTCUSD")
        return

    alias = args[0].upper().strip()
    pair = market_data.resolve_pair(alias)

    # Validate against Kraken
    msg = await update.message.reply_text(f"Validating `{pair}` with Kraken…", parse_mode=ParseMode.MARKDOWN)
    valid = await market_data.validate_pair(pair)
    if not valid:
        await msg.edit_text(
            f"❌ `{alias}` could not be resolved to a valid Kraken pair.\n"
            "Check the spelling or try the full Kraken pair name (e.g. `XXBTZUSD`).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    added = storage.add_pair(user_id, pair)
    if added:
        await msg.edit_text(f"✅ Added `{pair}` to your watchlist.", parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.edit_text(f"ℹ️ `{pair}` is already in your watchlist.", parse_mode=ParseMode.MARKDOWN)


async def cmd_delpair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text("Usage: /delpair <pair>  e.g. /delpair BTCUSD")
        return

    alias = args[0].upper().strip()
    pair = market_data.resolve_pair(alias)
    removed = storage.remove_pair(user_id, pair)

    if removed:
        await update.message.reply_text(f"🗑️ Removed `{pair}` from your watchlist.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"❌ `{pair}` was not in your watchlist.", parse_mode=ParseMode.MARKDOWN)


async def cmd_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    pairs = storage.get_pairs(user_id)

    if not pairs:
        await update.message.reply_text("Your watchlist is empty. Use /setpair to add pairs.")
        return

    # Fetch live prices
    prices = await market_data.fetch_prices(pairs)
    lines = ["📋 *Your watchlist*\n"]
    for p in pairs:
        price = prices.get(p)
        price_str = f"`{price:,.4f}`" if price is not None else "_unavailable_"
        lines.append(f"• `{p}`: {price_str}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_setalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse and store an alert rule.

    Price:   /setalert <pair> price <op> <value> [cooldown=<s>]
    Change:  /setalert <pair> change <op> <pct>% <window> [cooldown=<s>]
    """
    user_id = update.effective_user.id
    args = context.args

    if len(args) < 4:
        await update.message.reply_text(
            "Usage:\n"
            "  /setalert <pair> price <op> <value> [cooldown=<s>]\n"
            "  /setalert <pair> change <op> <pct>% <window> [cooldown=<s>]\n\n"
            "Examples:\n"
            "  /setalert BTCUSD price > 70000\n"
            "  /setalert ETHUSD change > 2% 15m cooldown=600"
        )
        return

    alias = args[0].upper().strip()
    pair = market_data.resolve_pair(alias)
    alert_type = args[1].lower()

    if alert_type == "price":
        # /setalert <pair> price <op> <value> [cooldown=<s>]
        if len(args) < 4:
            await update.message.reply_text("Price alert needs: <pair> price <op> <value>")
            return
        operator = args[2]
        if operator not in VALID_OPERATORS:
            await update.message.reply_text(f"❌ Invalid operator `{operator}`. Use one of: > < >= <=")
            return
        try:
            value = float(args[3].replace(",", ""))
        except ValueError:
            await update.message.reply_text(f"❌ Invalid price value: `{args[3]}`")
            return
        cooldown = _parse_cooldown(args[4:])
        alert_id = storage.add_alert(user_id, pair, "price", operator, value, None, cooldown)
        await update.message.reply_text(
            f"✅ Alert #{alert_id} set: `{pair}` price {operator} `{value:,.4f}` "
            f"(cooldown {cooldown}s)",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif alert_type == "change":
        # /setalert <pair> change <op> <pct>% <window> [cooldown=<s>]
        if len(args) < 5:
            await update.message.reply_text(
                "Change alert needs: <pair> change <op> <pct>% <window>\n"
                "e.g. /setalert BTCUSD change > 2% 15m"
            )
            return
        operator = args[2]
        if operator not in VALID_OPERATORS:
            await update.message.reply_text(f"❌ Invalid operator `{operator}`. Use one of: > < >= <=")
            return
        pct_str = args[3].rstrip("%")
        try:
            value = float(pct_str)
        except ValueError:
            await update.message.reply_text(f"❌ Invalid percentage value: `{args[3]}`")
            return
        window = args[4].lower()
        if window not in VALID_WINDOWS:
            await update.message.reply_text(
                f"❌ Invalid window `{window}`. Supported: {', '.join(sorted(VALID_WINDOWS))}"
            )
            return
        cooldown = _parse_cooldown(args[5:])
        alert_id = storage.add_alert(user_id, pair, "change", operator, value, window, cooldown)
        await update.message.reply_text(
            f"✅ Alert #{alert_id} set: `{pair}` change {operator} `{value:.2f}%` over {window} "
            f"(cooldown {cooldown}s)",
            parse_mode=ParseMode.MARKDOWN,
        )

    else:
        await update.message.reply_text(
            f"❌ Unknown alert type `{alert_type}`. Use `price` or `change`."
        )


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    alerts = storage.get_alerts(user_id)

    if not alerts:
        await update.message.reply_text("You have no active alerts. Use /setalert to create one.")
        return

    lines = ["🔔 *Your alerts*\n"]
    for a in alerts:
        if a["alert_type"] == "price":
            desc = f"price {a['operator']} `{a['value']:,.4f}`"
        else:
            desc = f"change {a['operator']} `{a['value']:.2f}%` over {a['window']}"
        cooldown_info = f"cooldown {a['cooldown']}s"
        lines.append(f"• *#{a['id']}* `{a['pair']}` — {desc} ({cooldown_info})")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_delalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text("Usage: /delalert <id>")
        return

    try:
        alert_id = int(args[0])
    except ValueError:
        await update.message.reply_text(f"❌ Invalid alert ID: `{args[0]}`")
        return

    removed = storage.remove_alert(user_id, alert_id)
    if removed:
        await update.message.reply_text(f"🗑️ Alert #{alert_id} deleted.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(
            f"❌ Alert #{alert_id} not found (or it belongs to another user)."
        )


# ---------------------------------------------------------------------------
# Background polling task
# ---------------------------------------------------------------------------

def _make_polling_loop(application: Application) -> "Callable[[], Coroutine[Any, Any, None]]":
    """Return a polling-loop coroutine that uses *application* to send alerts."""

    async def _send_alert(user_id: int, message: str) -> None:
        try:
            await application.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send alert to user %d: %s", user_id, exc)

    async def _loop() -> None:
        logger.info("Polling loop started (interval=%ds)", config.POLL_INTERVAL)
        while True:
            try:
                wl_pairs = storage.get_all_watched_pairs()
                alert_pairs = list({a["pair"] for a in storage.get_all_alerts()})
                all_pairs = list(set(wl_pairs + alert_pairs))

                if all_pairs:
                    prices = await market_data.fetch_prices(all_pairs)

                    for pair, price in prices.items():
                        storage.record_price(pair, price)

                    await alerts_engine.evaluate_alerts(prices, _send_alert)

                    storage.prune_price_history(max_age_seconds=7200)

            except Exception as exc:  # noqa: BLE001
                logger.error("Error in polling loop: %s", exc)

            await asyncio.sleep(config.POLL_INTERVAL)

    return _loop


# ---------------------------------------------------------------------------
# Application bootstrap
# ---------------------------------------------------------------------------

def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    storage.init_db()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setpair", cmd_setpair))
    app.add_handler(CommandHandler("delpair", cmd_delpair))
    app.add_handler(CommandHandler("pairs", cmd_pairs))
    app.add_handler(CommandHandler("setalert", cmd_setalert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("delalert", cmd_delalert))

    polling_loop = _make_polling_loop(app)

    async def _post_init(application: Application) -> None:
        asyncio.create_task(polling_loop())

    app.post_init = _post_init  # type: ignore[method-assign]

    logger.info("Starting bot…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

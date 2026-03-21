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
import html
import logging
import re
from collections.abc import Callable, Coroutine
from typing import Any, Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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
    "🚀 <b>Welcome to TradeWatch Bot</b>\n\n"

    "Your real-time crypto &amp; gold price alert system.\n"
    "Never miss a trade — get instant 🚨 notifications\n"
    "straight to Telegram.\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "⚡ <b>Start in 30 seconds</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "1️⃣  <b>Add a coin to watch</b>\n"
    "     /setpair BTCUSD\n\n"

    "2️⃣  <b>Set your price target</b>\n"
    "     /setalert BTCUSD price &gt; 90000\n\n"

    "3️⃣  <b>Relax</b> — you'll get a 🚨 alert\n"
    "     when the price hits your target!\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "📋 <b>Watchlist</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "  /setpair BTCUSD  ➜  📌 Add a pair\n"
    "  /delpair BTCUSD  ➜  🗑 Remove a pair\n"
    "  /pairs           ➜  💰 View live prices\n\n"

    "  🪙 <b>Crypto:</b> BTC · ETH · SOL · XRP\n"
    "     DOGE · ADA · DOT · LINK · and more\n"
    "  🥇 <b>Gold:</b>  /setpair GOLDUSD\n"
    "     <i>(PAXG — tracks real gold price)</i>\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "🔔 <b>Alerts</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "💲 <b>Price alert</b> — notify at exact price\n\n"

    "  <code>/setalert BTCUSD price &gt; 90000</code>\n"
    "  ↳ 📈 Tell me when BTC goes above $90k\n\n"
    "  <code>/setalert ETHUSD price &lt; 1800</code>\n"
    "  ↳ 📉 Tell me when ETH drops below $1.8k\n\n"
    "  <code>/setalert GOLDUSD price &gt; 2500</code>\n"
    "  ↳ 🥇 Tell me when Gold goes above $2,500\n\n"

    "📊 <b>% Change alert</b> — notify on big moves\n\n"

    "  <code>/setalert BTCUSD change &gt; 5% 1h</code>\n"
    "  ↳ 🔥 BTC moves 5%+ in the last hour\n\n"
    "  <code>/setalert SOLUSD change &lt; -3% 15m</code>\n"
    "  ↳ 💧 SOL drops 3%+ in 15 minutes\n\n"

    "  /alerts      ➜  📋 View your alerts\n"
    "  /delalert 1  ➜  🗑 Delete alert #1\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "⚙️ <b>Tips &amp; options</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "  📐 <b>Operators</b>   &gt;   &lt;   &gt;=   &lt;=\n"
    "  🕐 <b>Windows</b>     5m · 15m · 1h\n"
    "  ⏳ <b>Cooldown</b>    5 min default\n"
    "     Custom: add <code>cooldown=600</code>\n\n"

    "  💡 Case doesn't matter —\n"
    "     <code>btcusd</code> = <code>BTCUSD</code> = <code>BtcUsd</code>\n"
)

VALID_OPERATORS = {">", "<", ">=", "<="}
VALID_WINDOWS = {"5m", "15m", "1h"}
TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")


def _parse_cooldown(tokens: list[str], default: int = 300) -> int:
    for t in tokens:
        m = re.fullmatch(r"cooldown=(\d+)", t, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return default


def _is_valid_telegram_token(token: str) -> bool:
    t = token.strip()
    if not t:
        return False
    if t.lower() in {"your_bot_token_here", "changeme", "replace_me"}:
        return False
    return TOKEN_PATTERN.fullmatch(t) is not None


def _html_op(operator: str) -> str:
    """HTML-escape an operator string."""
    return html.escape(operator)


def _build_pairs_text(pairs: list[str], prices: Dict[str, float]) -> str:
    """Build the watchlist message text."""
    lines = [
        "📋  <b>WATCHLIST</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    for p in pairs:
        display = market_data.friendly_name(p)
        price = prices.get(p)
        price_str = market_data.fmt_price(price) if price is not None else "unavailable"
        lines.append(f"  <b>{display}</b>    <code>{price_str}</code>")

    lines.append(f"\n  {len(pairs)} pair{'s' if len(pairs) != 1 else ''} tracked")
    return "\n".join(lines)


def _build_alerts_text(
    alerts: list, prices: Dict[str, float]
) -> Tuple[str, InlineKeyboardMarkup]:
    """Build the alerts message text and inline keyboard."""
    lines = [
        f"🔔  <b>ACTIVE ALERTS ({len(alerts)})</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]

    keyboard_buttons: List[InlineKeyboardButton] = []

    for a in alerts:
        display = market_data.friendly_name(a["pair"])
        aid = a["id"]

        if a["alert_type"] == "price":
            trigger = f"Price {_html_op(a['operator'])} {market_data.fmt_price(a['value'])}"
            current = prices.get(a["pair"])
            if current is not None:
                distance_pct = abs((a["value"] - current) / current * 100)
                lines.append(
                    f"<b>#{aid}</b> ⏳ <b>{display}</b>\n"
                    f"   {trigger}\n"
                    f"   📍 Now: {market_data.fmt_price(current)}  ({distance_pct:.2f}% away)\n"
                    f"   🔁 Every {market_data.fmt_cooldown(a['cooldown'])}\n"
                )
            else:
                lines.append(
                    f"<b>#{aid}</b> ⏳ <b>{display}</b>\n"
                    f"   {trigger}\n"
                    f"   🔁 Every {market_data.fmt_cooldown(a['cooldown'])}\n"
                )
        else:
            trigger = f"Change {_html_op(a['operator'])} {a['value']:.2f}% in {a['window']}"
            lines.append(
                f"<b>#{aid}</b> ⏳ <b>{display}</b>\n"
                f"   {trigger}\n"
                f"   🔁 Every {market_data.fmt_cooldown(a['cooldown'])}\n"
            )

        keyboard_buttons.append(
            InlineKeyboardButton(f"🗑 #{aid}", callback_data=f"del_alert:{aid}")
        )

    keyboard_rows = [keyboard_buttons[i:i + 3] for i in range(0, len(keyboard_buttons), 3)]
    keyboard = InlineKeyboardMarkup(keyboard_rows)

    return "\n".join(lines), keyboard


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_setpair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "Usage: /setpair &lt;pair&gt;  e.g. /setpair BTCUSD",
            parse_mode=ParseMode.HTML,
        )
        return

    alias = args[0].upper().strip()
    pair = market_data.resolve_pair(alias)
    display = market_data.friendly_name(pair)

    msg = await update.message.reply_text(
        f"⏳ Validating <b>{display}</b> with Kraken…",
        parse_mode=ParseMode.HTML,
    )
    valid = await market_data.validate_pair(pair)
    if not valid:
        await msg.edit_text(
            f"❌ <b>{html.escape(alias)}</b> could not be resolved to a valid Kraken pair.\n\n"
            "Check the spelling or try the full Kraken pair name\n"
            "(e.g. <code>XXBTZUSD</code>).",
            parse_mode=ParseMode.HTML,
        )
        return

    added = storage.add_pair(user_id, pair)
    if added:
        prices = await market_data.fetch_prices([pair])
        price = prices.get(pair)
        price_line = f"\n   📍 Price: <code>{market_data.fmt_price(price)}</code>" if price else ""
        await msg.edit_text(
            f"✅ Added <b>{display}</b> to your watchlist.{price_line}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await msg.edit_text(
            f"ℹ️ <b>{display}</b> is already in your watchlist.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_delpair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "Usage: /delpair &lt;pair&gt;  e.g. /delpair BTCUSD",
            parse_mode=ParseMode.HTML,
        )
        return

    alias = args[0].upper().strip()
    pair = market_data.resolve_pair(alias)
    display = market_data.friendly_name(pair)
    removed = storage.remove_pair(user_id, pair)

    if removed:
        await update.message.reply_text(
            f"🗑️ Removed <b>{display}</b> from your watchlist.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"❌ <b>{display}</b> was not in your watchlist.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    pairs = storage.get_pairs(user_id)

    if not pairs:
        await update.message.reply_text(
            "📋 Your watchlist is empty.\n\n"
            "Add a pair: /setpair BTCUSD",
            parse_mode=ParseMode.HTML,
        )
        return

    prices = await market_data.fetch_prices(pairs)
    text = _build_pairs_text(pairs, prices)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_pairs")]
    ])
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def cmd_setalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse and store an alert rule.

    Price:   /setalert <pair> price <op> <value> [cooldown=<s>]
    Change:  /setalert <pair> change <op> <pct>% <window> [cooldown=<s>]
    """
    user_id = update.effective_user.id
    args = context.args

    if len(args) < 4:
        await update.message.reply_text(
            "⚙️ <b>ALERT SETUP</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Price alert:</b>\n"
            "  /setalert BTCUSD price &gt; 70000\n\n"
            "<b>Change alert:</b>\n"
            "  /setalert ETHUSD change &gt; 2% 15m\n\n"
            "<b>With cooldown:</b>\n"
            "  /setalert BTCUSD price &lt; 60000 cooldown=600",
            parse_mode=ParseMode.HTML,
        )
        return

    alias = args[0].upper().strip()
    pair = market_data.resolve_pair(alias)
    display = market_data.friendly_name(pair)
    alert_type = args[1].lower()

    if alert_type == "price":
        if len(args) < 4:
            await update.message.reply_text(
                "Price alert needs: &lt;pair&gt; price &lt;op&gt; &lt;value&gt;",
                parse_mode=ParseMode.HTML,
            )
            return
        operator = args[2]
        if operator not in VALID_OPERATORS:
            await update.message.reply_text(
                f"❌ Invalid operator <code>{html.escape(operator)}</code>\n"
                "Use: <code>&gt;</code>  <code>&lt;</code>  <code>&gt;=</code>  <code>&lt;=</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        try:
            value = float(args[3].replace(",", ""))
        except ValueError:
            await update.message.reply_text(
                f"❌ Invalid price value: <code>{html.escape(args[3])}</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        cooldown = _parse_cooldown(args[4:])
        alert_id = storage.add_alert(user_id, pair, "price", operator, value, None, cooldown)

        # Fetch current price for context
        prices = await market_data.fetch_prices([pair])
        current_price = prices.get(pair)

        text = (
            f"✅  <b>ALERT #{alert_id} CREATED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"  Pair:       <b>{display}</b>\n"
            f"  Trigger:    Price {_html_op(operator)} {market_data.fmt_price(value)}\n"
        )
        if current_price is not None:
            distance_pct = abs((value - current_price) / current_price * 100)
            text += (
                f"  Now:        {market_data.fmt_price(current_price)}\n"
                f"  Distance:   {distance_pct:.2f}% away\n"
            )
        text += f"  Cooldown:   {market_data.fmt_cooldown(cooldown)}"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 View all alerts", callback_data="view_alerts")]
        ])
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    elif alert_type == "change":
        if len(args) < 5:
            await update.message.reply_text(
                "Change alert needs: &lt;pair&gt; change &lt;op&gt; &lt;pct&gt;% &lt;window&gt;\n"
                "e.g. /setalert BTCUSD change &gt; 2% 15m",
                parse_mode=ParseMode.HTML,
            )
            return
        operator = args[2]
        if operator not in VALID_OPERATORS:
            await update.message.reply_text(
                f"❌ Invalid operator <code>{html.escape(operator)}</code>\n"
                "Use: <code>&gt;</code>  <code>&lt;</code>  <code>&gt;=</code>  <code>&lt;=</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        pct_str = args[3].rstrip("%")
        try:
            value = float(pct_str)
        except ValueError:
            await update.message.reply_text(
                f"❌ Invalid percentage: <code>{html.escape(args[3])}</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        window = args[4].lower()
        if window not in VALID_WINDOWS:
            await update.message.reply_text(
                f"❌ Invalid window <code>{html.escape(window)}</code>\n"
                "Supported: <code>5m</code>  <code>15m</code>  <code>1h</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        cooldown = _parse_cooldown(args[5:])
        alert_id = storage.add_alert(user_id, pair, "change", operator, value, window, cooldown)

        text = (
            f"✅  <b>ALERT #{alert_id} CREATED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"  Pair:       <b>{display}</b>\n"
            f"  Trigger:    Change {_html_op(operator)} {value:.2f}% in {window}\n"
            f"  Cooldown:   {market_data.fmt_cooldown(cooldown)}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 View all alerts", callback_data="view_alerts")]
        ])
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    else:
        await update.message.reply_text(
            f"❌ Unknown alert type <code>{html.escape(alert_type)}</code>\n"
            "Use <code>price</code> or <code>change</code>.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    alerts = storage.get_alerts(user_id)

    if not alerts:
        await update.message.reply_text(
            "🔔 You have no active alerts.\n\n"
            "Create one: /setalert BTCUSD price &gt; 70000",
            parse_mode=ParseMode.HTML,
        )
        return

    alert_pairs = list({a["pair"] for a in alerts})
    prices = await market_data.fetch_prices(alert_pairs)

    text, keyboard = _build_alerts_text(alerts, prices)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def cmd_delalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "Usage: /delalert &lt;id&gt;",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        alert_id = int(args[0])
    except ValueError:
        await update.message.reply_text(
            f"❌ Invalid alert ID: <code>{html.escape(args[0])}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    removed = storage.remove_alert(user_id, alert_id)
    if removed:
        await update.message.reply_text(
            f"🗑️ Alert <b>#{alert_id}</b> deleted.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"❌ Alert #{alert_id} not found (or belongs to another user).",
            parse_mode=ParseMode.HTML,
        )


# ---------------------------------------------------------------------------
# Callback query handler (inline buttons)
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "refresh_pairs":
        user_id = query.from_user.id
        pairs = storage.get_pairs(user_id)

        if not pairs:
            await query.edit_message_text(
                "📋 Your watchlist is empty.\n\nAdd a pair: /setpair BTCUSD",
                parse_mode=ParseMode.HTML,
            )
            return

        prices = await market_data.fetch_prices(pairs)
        text = _build_pairs_text(pairs, prices)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_pairs")]
        ])
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    elif data == "view_alerts":
        user_id = query.from_user.id
        alerts = storage.get_alerts(user_id)

        if not alerts:
            await query.edit_message_text(
                "🔔 You have no active alerts.\n\n"
                "Create one: /setalert BTCUSD price &gt; 70000",
                parse_mode=ParseMode.HTML,
            )
            return

        alert_pairs = list({a["pair"] for a in alerts})
        prices = await market_data.fetch_prices(alert_pairs)

        text, keyboard = _build_alerts_text(alerts, prices)

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    elif data.startswith("del_alert:"):
        user_id = query.from_user.id
        try:
            alert_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            return

        removed = storage.remove_alert(user_id, alert_id)
        if removed:
            await query.edit_message_text(
                f"🗑️ Alert <b>#{alert_id}</b> deleted.\n\n"
                "View remaining: /alerts",
                parse_mode=ParseMode.HTML,
            )
        else:
            await query.edit_message_text(
                f"❌ Alert #{alert_id} not found.",
                parse_mode=ParseMode.HTML,
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
                parse_mode=ParseMode.HTML,
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
    if not _is_valid_telegram_token(config.TELEGRAM_BOT_TOKEN):
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is missing or invalid. "
            "Set a real BotFather token in .env (format: <digits>:<secret>) and rerun."
        )

    storage.init_db()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setpair", cmd_setpair))
    app.add_handler(CommandHandler("delpair", cmd_delpair))
    app.add_handler(CommandHandler("pairs", cmd_pairs))
    app.add_handler(CommandHandler("setalert", cmd_setalert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("delalert", cmd_delalert))
    app.add_handler(CallbackQueryHandler(handle_callback))

    polling_loop = _make_polling_loop(app)

    async def _post_init(application: Application) -> None:
        asyncio.create_task(polling_loop())

    app.post_init = _post_init  # type: ignore[method-assign]

    logger.info("Starting bot…")
    # Python 3.14 no longer creates a default event loop implicitly.
    asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

# Telegram Signals & Alerts Bot

A multi-user Telegram bot that polls the [Kraken](https://www.kraken.com/) public REST API every 10 seconds and fires configurable price and percent-change alerts. **No order execution** — signals and alerts only.

---

## Features

| Feature | Detail |
|---------|--------|
| **Multi-user** | Each Telegram user manages their own watchlist and alerts |
| **Price alerts** | Fire when a pair's price crosses a threshold |
| **Change alerts** | Fire when a pair moves ±N% over a rolling window (5 m, 15 m, 1 h) |
| **Pair aliases** | Type `BTCUSD`, `ETHUSD`, `SOLUSD`, etc. — auto-mapped to Kraken pair names |
| **Cooldowns** | Configurable per-alert cooldown to avoid notification spam |
| **Persistence** | SQLite — state survives restarts |
| **Open to all** | No allowlist; any Telegram user can use the bot |

---

## Project layout

```
.
├── bot.py              # Telegram bot (entry point + command handlers)
├── market_data.py      # Kraken REST API client + pair-alias map
├── alerts_engine.py    # Alert rule evaluation
├── storage.py          # SQLite persistence layer
├── config.py           # Settings loaded from .env
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### 1. Create a bot

Talk to [@BotFather](https://t.me/BotFather) on Telegram and create a new bot.  Copy the **API token**.

### 2. Clone & install

```bash
git clone https://github.com/alimukhammad/Telegram-bot-telegram-fin.git
cd Telegram-bot-telegram-fin
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and set TELEGRAM_BOT_TOKEN
```

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *(required)* | Token from BotFather |
| `POLL_INTERVAL` | `10` | Seconds between Kraken polls |
| `DB_PATH` | `bot.db` | SQLite database file path |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### 4. Run

```bash
python bot.py
```

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show help |
| `/setpair <pair>` | Add a pair to your watchlist, e.g. `/setpair BTCUSD` |
| `/delpair <pair>` | Remove a pair from your watchlist |
| `/pairs` | List watchlist with live prices |
| `/setalert <pair> price <op> <value> [cooldown=<s>]` | Price threshold alert |
| `/setalert <pair> change <op> <pct>% <window> [cooldown=<s>]` | Percent-change alert |
| `/alerts` | List your active alerts |
| `/delalert <id>` | Delete an alert by its ID |

### Alert examples

```
/setalert BTCUSD price > 70000
/setalert BTCUSD price < 60000 cooldown=600
/setalert ETHUSD change > 2% 15m
/setalert SOLUSD change < -5% 1h cooldown=3600
```

Supported operators: `>` `<` `>=` `<=`

Supported change windows: `5m` `15m` `1h`

Default cooldown: **300 seconds** (5 minutes).

---

## Supported pair aliases

Common aliases are automatically translated to Kraken pair names:

| Alias | Kraken pair |
|-------|-------------|
| BTCUSD | XXBTZUSD |
| BTCUSDT | XBTUSDT |
| ETHUSD | XETHZUSD |
| ETHUSDT | ETHUSDT |
| SOLUSD | SOLUSD |
| XRPUSD | XXRPZUSD |
| … | … |

Full mapping is in `market_data.py`.  You can also pass a Kraken pair name directly (e.g. `XXBTZUSD`).

---

## Architecture notes

- **python-telegram-bot** (v21, asyncio) handles Telegram updates.
- A background `asyncio.Task` polls Kraken every `POLL_INTERVAL` seconds, records prices to SQLite, and evaluates all alert rules.
- Rolling-window change alerts compare the current price against the closest historical sample at `now − window`.
- Price history older than 2 hours is pruned automatically.


Quick Start

cd into the project root

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

set telegram token in .env TELEGRAM_BOT_TOKEN=your_real_token_from_botfather

python bot.py

in telegram bot open bot and send /start
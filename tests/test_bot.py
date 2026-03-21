"""Unit tests for storage, market_data, alerts_engine, and bot helpers."""
from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Use an in-memory SQLite database for all tests
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own fresh SQLite database file."""
    import config
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    import storage
    storage.init_db()
    yield


# ---------------------------------------------------------------------------
# Storage tests
# ---------------------------------------------------------------------------

class TestWatchlist:
    def test_add_and_get(self):
        import storage
        assert storage.add_pair(1, "XXBTZUSD") is True
        assert storage.get_pairs(1) == ["XXBTZUSD"]

    def test_add_duplicate(self):
        import storage
        storage.add_pair(1, "XXBTZUSD")
        assert storage.add_pair(1, "XXBTZUSD") is False

    def test_remove_existing(self):
        import storage
        storage.add_pair(1, "XXBTZUSD")
        assert storage.remove_pair(1, "XXBTZUSD") is True
        assert storage.get_pairs(1) == []

    def test_remove_nonexistent(self):
        import storage
        assert storage.remove_pair(1, "XXBTZUSD") is False

    def test_multiple_users_isolated(self):
        import storage
        storage.add_pair(1, "XXBTZUSD")
        storage.add_pair(2, "XETHZUSD")
        assert storage.get_pairs(1) == ["XXBTZUSD"]
        assert storage.get_pairs(2) == ["XETHZUSD"]

    def test_get_all_watched_pairs_dedup(self):
        import storage
        storage.add_pair(1, "XXBTZUSD")
        storage.add_pair(2, "XXBTZUSD")
        storage.add_pair(2, "XETHZUSD")
        all_pairs = storage.get_all_watched_pairs()
        assert sorted(all_pairs) == ["XETHZUSD", "XXBTZUSD"]

    def test_empty_watchlist(self):
        import storage
        assert storage.get_pairs(999) == []

    def test_add_multiple_pairs_one_user(self):
        import storage
        storage.add_pair(1, "XXBTZUSD")
        storage.add_pair(1, "XETHZUSD")
        storage.add_pair(1, "SOLUSD")
        pairs = storage.get_pairs(1)
        assert len(pairs) == 3
        assert "XXBTZUSD" in pairs
        assert "XETHZUSD" in pairs
        assert "SOLUSD" in pairs

    def test_add_gold_pair(self):
        import storage
        assert storage.add_pair(1, "PAXGUSD") is True
        assert storage.get_pairs(1) == ["PAXGUSD"]


class TestAlerts:
    def test_add_price_alert(self):
        import storage
        alert_id = storage.add_alert(1, "XXBTZUSD", "price", ">", 70000, None, 300)
        assert isinstance(alert_id, int)
        alerts = storage.get_alerts(1)
        assert len(alerts) == 1
        a = alerts[0]
        assert a["pair"] == "XXBTZUSD"
        assert a["alert_type"] == "price"
        assert a["operator"] == ">"
        assert a["value"] == 70000
        assert a["window"] is None
        assert a["cooldown"] == 300

    def test_add_change_alert(self):
        import storage
        storage.add_alert(1, "XXBTZUSD", "change", ">", 2.0, "15m", 600)
        alerts = storage.get_alerts(1)
        assert len(alerts) == 1
        assert alerts[0]["window"] == "15m"

    def test_remove_alert(self):
        import storage
        alert_id = storage.add_alert(1, "XXBTZUSD", "price", ">", 70000, None, 300)
        assert storage.remove_alert(1, alert_id) is True
        assert storage.get_alerts(1) == []

    def test_remove_other_users_alert(self):
        import storage
        alert_id = storage.add_alert(2, "XXBTZUSD", "price", ">", 70000, None, 300)
        assert storage.remove_alert(1, alert_id) is False

    def test_update_last_triggered(self):
        import storage
        alert_id = storage.add_alert(1, "XXBTZUSD", "price", ">", 70000, None, 300)
        before = time.time()
        storage.update_last_triggered(alert_id)
        alerts = storage.get_alerts(1)
        assert alerts[0]["last_triggered"] >= before

    def test_remove_nonexistent_alert(self):
        import storage
        assert storage.remove_alert(1, 9999) is False

    def test_multiple_alerts_same_user(self):
        import storage
        id1 = storage.add_alert(1, "XXBTZUSD", "price", ">", 70000, None, 300)
        id2 = storage.add_alert(1, "XETHZUSD", "price", "<", 2000, None, 600)
        id3 = storage.add_alert(1, "XXBTZUSD", "change", ">", 5.0, "1h", 300)
        alerts = storage.get_alerts(1)
        assert len(alerts) == 3
        assert id1 != id2 != id3

    def test_get_all_alerts_across_users(self):
        import storage
        storage.add_alert(1, "XXBTZUSD", "price", ">", 70000, None, 300)
        storage.add_alert(2, "XETHZUSD", "price", "<", 2000, None, 300)
        all_alerts = storage.get_all_alerts()
        assert len(all_alerts) == 2

    def test_alert_created_at_is_set(self):
        import storage
        before = time.time()
        storage.add_alert(1, "XXBTZUSD", "price", ">", 70000, None, 300)
        after = time.time()
        alerts = storage.get_alerts(1)
        assert before <= alerts[0]["created_at"] <= after

    def test_add_alert_all_operators(self):
        import storage
        for op in [">", "<", ">=", "<="]:
            aid = storage.add_alert(1, "XXBTZUSD", "price", op, 70000, None, 300)
            assert isinstance(aid, int)

    def test_add_gold_alert(self):
        import storage
        alert_id = storage.add_alert(1, "PAXGUSD", "price", ">", 2500, None, 300)
        alerts = storage.get_alerts(1)
        assert alerts[0]["pair"] == "PAXGUSD"


class TestPriceHistory:
    def test_record_and_retrieve(self):
        import storage
        t = time.time()
        storage.record_price("XXBTZUSD", 65000.0)
        price = storage.get_price_at("XXBTZUSD", t + 1)
        assert price == pytest.approx(65000.0)

    def test_get_price_at_returns_closest_before(self):
        import storage
        t = time.time()
        storage.record_price("XXBTZUSD", 60000.0)
        with storage._db() as conn:
            conn.execute(
                "INSERT INTO price_history(pair, price, ts) VALUES (?, ?, ?)",
                ("XXBTZUSD", 70000.0, t + 100),
            )
        price = storage.get_price_at("XXBTZUSD", t + 50)
        assert price == pytest.approx(60000.0)

    def test_prune_removes_old(self):
        import storage
        with storage._db() as conn:
            conn.execute(
                "INSERT INTO price_history(pair, price, ts) VALUES (?, ?, ?)",
                ("XXBTZUSD", 50000.0, time.time() - 10000),
            )
        storage.prune_price_history(max_age_seconds=100)
        price = storage.get_price_at("XXBTZUSD", time.time())
        assert price is None

    def test_no_price_returns_none(self):
        import storage
        price = storage.get_price_at("XXBTZUSD", time.time())
        assert price is None

    def test_multiple_prices_same_pair(self):
        import storage
        t = time.time()
        with storage._db() as conn:
            conn.execute(
                "INSERT INTO price_history(pair, price, ts) VALUES (?, ?, ?)",
                ("XXBTZUSD", 60000.0, t - 200),
            )
            conn.execute(
                "INSERT INTO price_history(pair, price, ts) VALUES (?, ?, ?)",
                ("XXBTZUSD", 65000.0, t - 100),
            )
            conn.execute(
                "INSERT INTO price_history(pair, price, ts) VALUES (?, ?, ?)",
                ("XXBTZUSD", 70000.0, t),
            )
        # Should get the most recent one at or before t - 50
        price = storage.get_price_at("XXBTZUSD", t - 50)
        assert price == pytest.approx(65000.0)

    def test_prune_keeps_recent(self):
        import storage
        storage.record_price("XXBTZUSD", 80000.0)
        storage.prune_price_history(max_age_seconds=100)
        price = storage.get_price_at("XXBTZUSD", time.time() + 1)
        assert price == pytest.approx(80000.0)


# ---------------------------------------------------------------------------
# Market data tests (alias mapping only – no HTTP)
# ---------------------------------------------------------------------------

class TestPairAliases:
    def test_btcusd(self):
        from market_data import resolve_pair
        assert resolve_pair("BTCUSD") == "XXBTZUSD"

    def test_btcusdt(self):
        from market_data import resolve_pair
        assert resolve_pair("BTCUSDT") == "XBTUSDT"

    def test_ethusd(self):
        from market_data import resolve_pair
        assert resolve_pair("ETHUSD") == "XETHZUSD"

    def test_solusd(self):
        from market_data import resolve_pair
        assert resolve_pair("SOLUSD") == "SOLUSD"

    def test_case_insensitive(self):
        from market_data import resolve_pair
        assert resolve_pair("btcusd") == "XXBTZUSD"
        assert resolve_pair("BtcUsD") == "XXBTZUSD"

    def test_unknown_passthrough(self):
        from market_data import resolve_pair
        assert resolve_pair("SOMEPAIR") == "SOMEPAIR"

    def test_xrpusd(self):
        from market_data import resolve_pair
        assert resolve_pair("XRPUSD") == "XXRPZUSD"

    def test_goldusd_alias(self):
        from market_data import resolve_pair
        assert resolve_pair("GOLDUSD") == "PAXGUSD"

    def test_goldusd_case_insensitive(self):
        from market_data import resolve_pair
        assert resolve_pair("goldusd") == "PAXGUSD"
        assert resolve_pair("GoldUsd") == "PAXGUSD"

    def test_paxgusd_direct(self):
        from market_data import resolve_pair
        assert resolve_pair("PAXGUSD") == "PAXGUSD"

    def test_paxgusdt(self):
        from market_data import resolve_pair
        assert resolve_pair("PAXGUSDT") == "PAXGUSDT"

    def test_all_aliases_resolve_uppercase(self):
        """Every alias should resolve to an uppercase Kraken pair."""
        from market_data import _ALIAS_MAP
        for alias, pair in _ALIAS_MAP.items():
            assert pair == pair.upper(), f"Alias {alias} maps to non-uppercase {pair}"

    def test_dogecoin(self):
        from market_data import resolve_pair
        assert resolve_pair("DOGEUSD") == "XDGUSD"

    def test_ethbtc_and_ethxbt(self):
        from market_data import resolve_pair
        assert resolve_pair("ETHBTC") == "XETHXXBT"
        assert resolve_pair("ETHXBT") == "XETHXXBT"

    def test_whitespace_stripped(self):
        from market_data import resolve_pair
        assert resolve_pair("  BTCUSD  ") == "XXBTZUSD"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

class TestFriendlyName:
    def test_known_pairs(self):
        from market_data import friendly_name
        assert friendly_name("XXBTZUSD") == "BTC/USD"
        assert friendly_name("XETHZUSD") == "ETH/USD"
        assert friendly_name("SOLUSD") == "SOL/USD"
        assert friendly_name("XXRPZUSD") == "XRP/USD"

    def test_gold_display(self):
        from market_data import friendly_name
        assert friendly_name("PAXGUSD") == "GOLD/USD"
        assert friendly_name("PAXGUSDT") == "GOLD/USDT"

    def test_unknown_pair_returns_as_is(self):
        from market_data import friendly_name
        assert friendly_name("FAKEPAIR") == "FAKEPAIR"

    def test_all_display_map_entries_have_slash(self):
        from market_data import _DISPLAY_MAP
        for pair, display in _DISPLAY_MAP.items():
            assert "/" in display, f"Display name for {pair} missing slash: {display}"


class TestFmtPrice:
    def test_large_price(self):
        from market_data import fmt_price
        assert fmt_price(83412.50) == "$83,412.50"

    def test_medium_price(self):
        from market_data import fmt_price
        assert fmt_price(1927.34) == "$1,927.34"

    def test_small_price_above_one(self):
        from market_data import fmt_price
        assert fmt_price(1.50) == "$1.50"

    def test_sub_dollar_price(self):
        from market_data import fmt_price
        result = fmt_price(0.083412)
        assert result.startswith("$0.08")
        assert len(result) > 5  # has more decimals

    def test_exact_one(self):
        from market_data import fmt_price
        assert fmt_price(1.0) == "$1.00"

    def test_zero(self):
        from market_data import fmt_price
        result = fmt_price(0.0)
        assert "$0" in result

    def test_very_small_price(self):
        from market_data import fmt_price
        result = fmt_price(0.000001)
        assert "$0.000001" == result


class TestFmtCooldown:
    def test_seconds(self):
        from market_data import fmt_cooldown
        assert fmt_cooldown(30) == "30s"

    def test_exact_minutes(self):
        from market_data import fmt_cooldown
        assert fmt_cooldown(300) == "5 min"
        assert fmt_cooldown(600) == "10 min"
        assert fmt_cooldown(60) == "1 min"

    def test_mixed_minutes_seconds(self):
        from market_data import fmt_cooldown
        assert fmt_cooldown(90) == "1m 30s"
        assert fmt_cooldown(150) == "2m 30s"

    def test_zero(self):
        from market_data import fmt_cooldown
        assert fmt_cooldown(0) == "0s"

    def test_one_hour(self):
        from market_data import fmt_cooldown
        assert fmt_cooldown(3600) == "60 min"


# ---------------------------------------------------------------------------
# Alerts engine tests (no HTTP, no Telegram)
# ---------------------------------------------------------------------------

class TestAlertsEngine:
    def test_price_alert_fires(self):
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", ">", 60000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 65000.0}, capture)

        asyncio.run(run())
        assert len(fired) == 1
        assert fired[0][0] == 42
        assert "65" in fired[0][1]  # price appears in message

    def test_price_alert_does_not_fire_wrong_side(self):
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", ">", 70000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 65000.0}, capture)

        asyncio.run(run())
        assert fired == []

    def test_price_alert_cooldown(self):
        import storage
        import alerts_engine
        fired = []

        async def run():
            alert_id = storage.add_alert(42, "XXBTZUSD", "price", ">", 60000, None, 3600)
            storage.update_last_triggered(alert_id)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 65000.0}, capture)

        asyncio.run(run())
        assert fired == []

    def test_change_alert_fires(self):
        import storage
        import alerts_engine
        fired = []

        async def run():
            t = time.time()
            with storage._db() as conn:
                conn.execute(
                    "INSERT INTO price_history(pair, price, ts) VALUES (?, ?, ?)",
                    ("XXBTZUSD", 60000.0, t - 305),
                )

            storage.add_alert(42, "XXBTZUSD", "change", ">", 3.0, "5m", 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            # 60000 → 62000 = +3.33% > 3%
            await alerts_engine.evaluate_alerts({"XXBTZUSD": 62000.0}, capture)

        asyncio.run(run())
        assert len(fired) == 1

    def test_change_alert_no_history(self):
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "change", ">", 3.0, "5m", 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 62000.0}, capture)

        asyncio.run(run())
        assert fired == []

    def test_missing_pair_skipped(self):
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", ">", 60000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XETHZUSD": 3000.0}, capture)

        asyncio.run(run())
        assert fired == []

    def test_price_alert_html_format(self):
        """Alert messages should use HTML formatting."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", ">", 60000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 65000.0}, capture)

        asyncio.run(run())
        msg = fired[0][1]
        assert "<b>" in msg  # HTML bold tags
        assert "PRICE ALERT TRIGGERED" in msg
        assert "BTC/USD" in msg  # friendly name
        assert "$65,000.00" in msg  # formatted price
        assert "Exceeded by" in msg
        assert "&gt;" in msg  # HTML-escaped operator

    def test_change_alert_html_format(self):
        """Change alert messages should use HTML formatting."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            t = time.time()
            with storage._db() as conn:
                conn.execute(
                    "INSERT INTO price_history(pair, price, ts) VALUES (?, ?, ?)",
                    ("XXBTZUSD", 60000.0, t - 305),
                )
            storage.add_alert(42, "XXBTZUSD", "change", ">", 3.0, "5m", 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 62000.0}, capture)

        asyncio.run(run())
        msg = fired[0][1]
        assert "CHANGE ALERT TRIGGERED" in msg
        assert "BTC/USD" in msg
        assert "📈" in msg  # up direction
        assert "5m" in msg

    def test_price_alert_exceeded_amount(self):
        """Alert should show how much the price exceeded the target."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", ">", 60000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 61000.0}, capture)

        asyncio.run(run())
        msg = fired[0][1]
        assert "$1,000.00" in msg  # exceeded amount
        assert "1.67%" in msg  # exceeded percentage

    def test_price_alert_less_than(self):
        """Test < operator fires correctly."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", "<", 60000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 55000.0}, capture)

        asyncio.run(run())
        assert len(fired) == 1
        assert "&lt;" in fired[0][1]

    def test_price_alert_gte(self):
        """Test >= operator fires at exact value."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", ">=", 60000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 60000.0}, capture)

        asyncio.run(run())
        assert len(fired) == 1

    def test_price_alert_lte(self):
        """Test <= operator fires at exact value."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", "<=", 60000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 60000.0}, capture)

        asyncio.run(run())
        assert len(fired) == 1

    def test_cooldown_next_alert_text(self):
        """Alert should show when the next alert will fire."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", ">", 60000, None, 300)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 65000.0}, capture)

        asyncio.run(run())
        assert "5 min" in fired[0][1]

    def test_change_alert_negative_direction(self):
        """Negative price change should show down emoji."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            t = time.time()
            with storage._db() as conn:
                conn.execute(
                    "INSERT INTO price_history(pair, price, ts) VALUES (?, ?, ?)",
                    ("XXBTZUSD", 60000.0, t - 305),
                )
            storage.add_alert(42, "XXBTZUSD", "change", "<", -3.0, "5m", 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            # 60000 → 57000 = -5%
            await alerts_engine.evaluate_alerts({"XXBTZUSD": 57000.0}, capture)

        asyncio.run(run())
        assert len(fired) == 1
        assert "📉" in fired[0][1]

    def test_unknown_window_skipped(self):
        """Alerts with unknown window should be skipped without error."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "change", ">", 3.0, "99h", 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 65000.0}, capture)

        asyncio.run(run())
        assert fired == []

    def test_multiple_alerts_fire_independently(self):
        """Multiple alerts for different conditions should fire independently."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", ">", 60000, None, 0)
            storage.add_alert(42, "XETHZUSD", "price", "<", 2000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts(
                {"XXBTZUSD": 65000.0, "XETHZUSD": 1800.0}, capture
            )

        asyncio.run(run())
        assert len(fired) == 2

    def test_gold_alert_fires(self):
        """Gold (PAXG) alerts should fire with GOLD/USD display name."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "PAXGUSD", "price", ">", 2400, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"PAXGUSD": 2550.0}, capture)

        asyncio.run(run())
        assert len(fired) == 1
        assert "GOLD/USD" in fired[0][1]
        assert "$2,550.00" in fired[0][1]

    def test_zero_cooldown_allows_repeat(self):
        """With cooldown=0, alert should fire every evaluation."""
        import storage
        import alerts_engine
        fired = []

        async def run():
            storage.add_alert(42, "XXBTZUSD", "price", ">", 60000, None, 0)

            async def capture(uid, msg):
                fired.append((uid, msg))

            await alerts_engine.evaluate_alerts({"XXBTZUSD": 65000.0}, capture)
            await alerts_engine.evaluate_alerts({"XXBTZUSD": 65000.0}, capture)

        asyncio.run(run())
        # Second call might be blocked by last_triggered being very recent with cooldown=0
        # cooldown=0 means (now - last_triggered < 0) is always False, so it should fire
        assert len(fired) == 2


# ---------------------------------------------------------------------------
# Bot helper tests
# ---------------------------------------------------------------------------

class TestBotHelpers:
    def test_parse_cooldown_default(self):
        from bot import _parse_cooldown
        assert _parse_cooldown([]) == 300

    def test_parse_cooldown_custom(self):
        from bot import _parse_cooldown
        assert _parse_cooldown(["cooldown=600"]) == 600

    def test_parse_cooldown_case_insensitive(self):
        from bot import _parse_cooldown
        assert _parse_cooldown(["COOLDOWN=120"]) == 120
        assert _parse_cooldown(["Cooldown=900"]) == 900

    def test_parse_cooldown_among_other_tokens(self):
        from bot import _parse_cooldown
        assert _parse_cooldown(["extra", "cooldown=450", "stuff"]) == 450

    def test_parse_cooldown_no_match(self):
        from bot import _parse_cooldown
        assert _parse_cooldown(["notcooldown=100"]) == 300

    def test_is_valid_telegram_token_valid(self):
        from bot import _is_valid_telegram_token
        assert _is_valid_telegram_token("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11") is True

    def test_is_valid_telegram_token_empty(self):
        from bot import _is_valid_telegram_token
        assert _is_valid_telegram_token("") is False

    def test_is_valid_telegram_token_placeholder(self):
        from bot import _is_valid_telegram_token
        assert _is_valid_telegram_token("your_bot_token_here") is False
        assert _is_valid_telegram_token("changeme") is False
        assert _is_valid_telegram_token("replace_me") is False

    def test_is_valid_telegram_token_bad_format(self):
        from bot import _is_valid_telegram_token
        assert _is_valid_telegram_token("not_a_token") is False
        assert _is_valid_telegram_token("12345") is False

    def test_html_op_escapes(self):
        from bot import _html_op
        assert _html_op(">") == "&gt;"
        assert _html_op("<") == "&lt;"
        assert _html_op(">=") == "&gt;="
        assert _html_op("<=") == "&lt;="

    def test_build_pairs_text(self):
        from bot import _build_pairs_text
        text = _build_pairs_text(
            ["XXBTZUSD", "XETHZUSD"],
            {"XXBTZUSD": 83000.0, "XETHZUSD": 1900.0},
        )
        assert "BTC/USD" in text
        assert "ETH/USD" in text
        assert "$83,000.00" in text
        assert "$1,900.00" in text
        assert "2 pairs tracked" in text

    def test_build_pairs_text_single(self):
        from bot import _build_pairs_text
        text = _build_pairs_text(["XXBTZUSD"], {"XXBTZUSD": 83000.0})
        assert "1 pair tracked" in text  # singular

    def test_build_pairs_text_unavailable_price(self):
        from bot import _build_pairs_text
        text = _build_pairs_text(["XXBTZUSD"], {})
        assert "unavailable" in text

    def test_build_pairs_text_gold(self):
        from bot import _build_pairs_text
        text = _build_pairs_text(["PAXGUSD"], {"PAXGUSD": 2450.0})
        assert "GOLD/USD" in text
        assert "$2,450.00" in text

    def test_build_alerts_text_price_alert(self):
        import storage
        from bot import _build_alerts_text
        storage.add_alert(1, "XXBTZUSD", "price", ">", 90000, None, 300)
        alerts = storage.get_alerts(1)
        text, keyboard = _build_alerts_text(
            alerts, {"XXBTZUSD": 83000.0}
        )
        assert "BTC/USD" in text
        assert "$90,000.00" in text
        assert "$83,000.00" in text
        assert "% away" in text
        assert "5 min" in text
        assert len(keyboard.inline_keyboard) > 0

    def test_build_alerts_text_change_alert(self):
        import storage
        from bot import _build_alerts_text
        storage.add_alert(1, "XETHZUSD", "change", ">", 5.0, "1h", 600)
        alerts = storage.get_alerts(1)
        text, keyboard = _build_alerts_text(alerts, {})
        assert "ETH/USD" in text
        assert "5.00%" in text
        assert "1h" in text
        assert "10 min" in text

    def test_build_alerts_text_no_price_available(self):
        """Alerts text should still render when price is unavailable."""
        import storage
        from bot import _build_alerts_text
        storage.add_alert(1, "XXBTZUSD", "price", ">", 90000, None, 300)
        alerts = storage.get_alerts(1)
        text, keyboard = _build_alerts_text(alerts, {})
        assert "BTC/USD" in text
        assert "$90,000.00" in text
        # Should NOT have "away" when no current price
        assert "away" not in text

    def test_build_alerts_text_multiple_alerts(self):
        import storage
        from bot import _build_alerts_text
        storage.add_alert(1, "XXBTZUSD", "price", ">", 90000, None, 300)
        storage.add_alert(1, "XETHZUSD", "price", "<", 2000, None, 600)
        storage.add_alert(1, "PAXGUSD", "price", ">", 2500, None, 300)
        alerts = storage.get_alerts(1)
        text, keyboard = _build_alerts_text(alerts, {})
        assert "ACTIVE ALERTS (3)" in text
        assert "BTC/USD" in text
        assert "ETH/USD" in text
        assert "GOLD/USD" in text
        # 3 buttons, in rows of 3
        total_buttons = sum(len(row) for row in keyboard.inline_keyboard)
        assert total_buttons == 3

    def test_build_alerts_text_delete_buttons(self):
        import storage
        from bot import _build_alerts_text
        aid = storage.add_alert(1, "XXBTZUSD", "price", ">", 90000, None, 300)
        alerts = storage.get_alerts(1)
        _, keyboard = _build_alerts_text(alerts, {})
        button = keyboard.inline_keyboard[0][0]
        assert f"del_alert:{aid}" == button.callback_data

    def test_help_text_contains_key_sections(self):
        from bot import HELP_TEXT
        assert "TradeWatch Bot" in HELP_TEXT
        assert "GOLDUSD" in HELP_TEXT
        assert "BTCUSD" in HELP_TEXT
        assert "/setpair" in HELP_TEXT
        assert "/setalert" in HELP_TEXT
        assert "/alerts" in HELP_TEXT
        assert "/delalert" in HELP_TEXT
        assert "PAXG" in HELP_TEXT

    def test_help_text_valid_html(self):
        """HELP_TEXT should have matching HTML tags."""
        from bot import HELP_TEXT
        assert HELP_TEXT.count("<b>") == HELP_TEXT.count("</b>")
        assert HELP_TEXT.count("<i>") == HELP_TEXT.count("</i>")
        assert HELP_TEXT.count("<code>") == HELP_TEXT.count("</code>")


# ---------------------------------------------------------------------------
# Compare function edge cases
# ---------------------------------------------------------------------------

class TestCompare:
    def test_all_operators(self):
        from alerts_engine import _compare
        assert _compare(10, ">", 5) is True
        assert _compare(5, ">", 10) is False
        assert _compare(5, "<", 10) is True
        assert _compare(10, "<", 5) is False
        assert _compare(10, ">=", 10) is True
        assert _compare(10, ">=", 5) is True
        assert _compare(5, ">=", 10) is False
        assert _compare(10, "<=", 10) is True
        assert _compare(5, "<=", 10) is True
        assert _compare(10, "<=", 5) is False

    def test_invalid_operator(self):
        from alerts_engine import _compare
        assert _compare(10, "==", 10) is False
        assert _compare(10, "!=", 5) is False

    def test_negative_values(self):
        from alerts_engine import _compare
        assert _compare(-5, "<", 0) is True
        assert _compare(-5, ">", -10) is True

    def test_float_precision(self):
        from alerts_engine import _compare
        assert _compare(0.1 + 0.2, ">", 0.3) is True  # floating point


# ---------------------------------------------------------------------------
# Alias/display map consistency
# ---------------------------------------------------------------------------

class TestMapConsistency:
    def test_every_alias_target_has_display_name(self):
        """Every Kraken pair that aliases resolve to should have a display name."""
        from market_data import _ALIAS_MAP, _DISPLAY_MAP
        missing = []
        for alias, kraken_pair in _ALIAS_MAP.items():
            if kraken_pair not in _DISPLAY_MAP:
                missing.append(f"{alias} -> {kraken_pair}")
        assert missing == [], f"Missing display names for: {missing}"

    def test_display_map_covers_all_unique_alias_targets(self):
        """All unique Kraken pairs from aliases should have display entries."""
        from market_data import _ALIAS_MAP, _DISPLAY_MAP
        targets = set(_ALIAS_MAP.values())
        for target in targets:
            assert target in _DISPLAY_MAP, f"No display name for {target}"

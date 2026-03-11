"""Unit tests for storage, market_data, and alerts_engine."""
from __future__ import annotations

import asyncio
import os
import time

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

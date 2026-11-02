import json
import time

import pytest

from app.services import signal_notifier, user_preferences


class _FakeBot:
    """Stands in for SignalNotifier: serves queued getUpdates and records every call."""

    def __init__(self, updates):
        self.updates = updates
        self.calls = []

    def _telegram_api(self, token, method, data, files=None):
        self.calls.append((token, method, data))
        if method == "getUpdates":
            return True, [] if "offset" in data else self.updates
        if method == "getMe":
            return True, {"username": "xtrade_trading_bot"}
        return True, {}


@pytest.fixture
def db(monkeypatch):
    """In-memory qd_users.notification_settings keyed by user id."""
    rows = {7: json.dumps({"default_channels": ["browser"], "telegram_bot_token": "old-user-bot"}), 8: "{}"}

    class Cursor:
        def execute(self, sql, params):
            rows[params[1]] = params[0]

        def close(self):
            pass

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return Cursor()

        def commit(self):
            pass

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "platform-token")
    monkeypatch.setattr(user_preferences, "get_db_connection", Conn)
    monkeypatch.setattr(
        user_preferences,
        "_fetch_user_settings_row",
        lambda uid: {"notification_settings": rows[uid], "email": ""} if uid in rows else None,
    )
    return rows


def _use_bot(monkeypatch, updates):
    bot = _FakeBot(updates)
    monkeypatch.setattr(user_preferences, "SignalNotifier", lambda: bot)
    user_preferences._telegram_bot_username.cache_clear()
    return bot


def test_start_with_link_code_binds_the_chat_to_its_user(monkeypatch, db):
    bot = _use_bot(monkeypatch, [])
    link = user_preferences.create_telegram_link(7)
    assert link["url"] == f"https://t.me/xtrade_trading_bot?start={link['code']}"

    bot.updates = [
        {"update_id": 40, "message": {"text": "/start", "chat": {"id": 1}}},
        {"update_id": 41, "message": {"text": f"/start {link['code']}", "chat": {"id": 555}}},
        {"update_id": 42, "message": {"text": "/start 8_123_forged", "chat": {"id": 666}}},
    ]
    assert user_preferences.telegram_link_status(7, link["code"]) == {"linked": True, "chat_id": "555"}
    saved = json.loads(db[7])
    assert saved["telegram_chat_id"] == "555"
    assert "telegram_bot_token" not in saved  # the platform bot owns the chat now
    assert db[8] == "{}"  # a forged code binds nobody
    assert ("platform-token", "getUpdates", {"offset": 43, "limit": 1, "timeout": 0}) in bot.calls

    # The same /start seen again (another poller) neither rebinds nor re-greets.
    sent = [c for c in bot.calls if c[1] == "sendMessage"]
    assert user_preferences.sync_telegram_links() == 0
    assert [c for c in bot.calls if c[1] == "sendMessage"] == sent


def test_link_code_is_bound_to_its_user_and_expires(monkeypatch, db):
    _use_bot(monkeypatch, [])
    code = user_preferences.create_telegram_link(7)["code"]
    with pytest.raises(ValueError):
        user_preferences.telegram_link_status(8, code)
    assert user_preferences.telegram_link_status(7, code) == {"linked": False, "chat_id": ""}

    old = int(time.time()) - user_preferences.TELEGRAM_LINK_TTL_SEC - 5
    stale = f"7_{old}_{user_preferences._telegram_link_sig(7, old)}"
    assert user_preferences._verify_telegram_link_code(stale) is None


def test_platform_token_overrides_per_user_bot(monkeypatch):
    seen = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "platform-token")
    monkeypatch.setattr(signal_notifier.requests, "post", lambda url, **kw: seen.append(url) or _Resp())
    assert signal_notifier.SignalNotifier()._telegram_api("user-token", "sendMessage", {})[0]
    assert seen == ["https://api.telegram.org/botplatform-token/sendMessage"]

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert signal_notifier.SignalNotifier()._telegram_api("", "sendMessage", {}) == (False, "missing_telegram_bot_token")


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"result": {}}

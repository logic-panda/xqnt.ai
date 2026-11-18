"""Forex provider windows must not depend on the container TZ (prod runs Asia/Shanghai)."""
import os
import time
from datetime import timezone
from unittest import mock

import pandas as pd
import pytest

from app.data_sources import forex
from app.data_sources.forex import ForexDataSource


@pytest.fixture
def shanghai_tz():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def test_yfinance_window_is_not_shifted_by_local_tz(shanghai_tz):
    captured = {}

    class FakeTicker:
        def __init__(self, sym):
            pass

        def history(self, start, end, interval):
            # yfinance reads naive datetimes in exchange time (~UTC for =X pairs).
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            captured["start"] = start.timestamp()
            return pd.DataFrame()

    with mock.patch.object(forex.yf, "Ticker", FakeTicker):
        ForexDataSource.__new__(ForexDataSource)._get_kline_yfinance("NZDUSD", "5m", 3)

    # limit=3 x 5m x 1.5 = 22.5 minutes before now, never in the future.
    assert abs(captured["start"] - (time.time() - 1350)) < 60


def test_twelvedata_times_are_parsed_as_utc(shanghai_tz):
    payload = {"values": [{"datetime": "2026-11-18 01:25:00", "open": "1", "high": "1", "low": "1", "close": "1"}]}
    with mock.patch.object(forex, "_get_td_api_key", return_value="k"), \
         mock.patch.object(forex, "_td_request", return_value=payload) as req:
        bars = ForexDataSource.__new__(ForexDataSource)._get_kline_twelvedata("NZDUSD", "5m", 3)

    assert req.call_args[0][1]["timezone"] == "UTC"
    assert bars[0]["time"] == 1794965100  # 2026-11-18T01:25:00Z

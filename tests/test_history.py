from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from mas.history import warmup_history
from mas.scenario import load_scenario

CONFIG = load_scenario(Path(__file__).resolve().parent.parent / "scenarios" / "default.json")
STATION = CONFIG.stations[0]


def history(config=CONFIG, station=STATION, days=3, seed=1):
    return warmup_history(config, station, days, np.random.default_rng(seed))


def test_history_length_is_days_times_24():
    assert len(history(days=3)) == 72
    assert len(history(days=1)) == 24


def test_history_is_reproducible_by_seed():
    assert history(seed=5) == history(seed=5)


def test_history_depends_on_seed():
    assert history(seed=5) != history(seed=6)


def test_history_follows_daily_profile():
    values = np.array(history(days=5)).reshape(5, 24).mean(axis=0)
    assert values[17:21].mean() > 3 * values[0:7].mean()
    assert values[7:10].mean() > values[10:17].mean()


def test_history_is_within_station_power():
    values = history(days=3)
    assert min(values) >= 0.0
    assert max(values) <= STATION.max_power_kw


def test_history_scales_with_traffic():
    busy = replace(CONFIG, ev_per_day=CONFIG.ev_per_day * 3)
    assert sum(history(busy)) > 2.2 * sum(history(CONFIG))


def test_no_traffic_gives_zero_history():
    empty = replace(CONFIG, ev_per_day=0)
    assert history(empty) == [0.0] * 72


def test_station_share_depends_on_power():
    big = history(station=CONFIG.stations[0])
    small = history(station=CONFIG.stations[6])
    assert sum(big) > sum(small)


def test_history_requires_at_least_one_day():
    with pytest.raises(ValueError):
        history(days=0)
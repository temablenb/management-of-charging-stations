import numpy as np
import pytest

from mas.bus import MessageBus
from mas.forecast import peak_hours
from mas.scenario import StationConfig
from mas.station_agent import StationAgent


def make_station(power=100.0):
    return StationAgent(MessageBus(), StationConfig("st-1", power, "CCS"))


def daily_pattern(days):
    hours = np.arange(24 * days)
    return list(50 + 20 * np.sin(2 * np.pi * (hours - 6) / 24))


def test_peak_hours_empty_forecast():
    assert peak_hours((), 0) == ()


def test_peak_hours_flat_forecast_has_no_peaks():
    assert peak_hours((10.0,) * 24, 0) == ()


def test_peak_hours_finds_hours_above_threshold():
    forecast = (10.0,) * 24
    forecast = forecast[:7] + (40.0,) + forecast[8:]
    assert peak_hours(forecast, 0) == (7,)


def test_peak_hours_shift_by_start_hour():
    forecast = (10.0,) * 24
    forecast = forecast[:3] + (40.0,) + forecast[4:]
    assert peak_hours(forecast, 20) == (23,)


def test_peak_hours_are_unique_and_sorted():
    forecast = (10.0,) * 48
    forecast = forecast[:30] + (60.0,) + forecast[31:]
    forecast = forecast[:6] + (60.0,) + forecast[7:]
    assert peak_hours(forecast, 0) == (6,)


def test_record_load_averages_over_hour():
    station = make_station()
    for tick, load in enumerate((10.0, 20.0, 30.0, 40.0)):
        station.record_load(tick, load)
    assert station.hourly_history == [25.0]


def test_record_load_collects_hours_in_order():
    station = make_station()
    for tick in range(8):
        station.record_load(tick, 10.0 if tick < 4 else 30.0)
    assert station.hourly_history == [10.0, 30.0]


def test_record_load_does_not_close_incomplete_hour():
    station = make_station()
    for tick in range(3):
        station.record_load(tick, 10.0)
    assert station.hourly_history == []


def test_record_load_rejects_negative_load():
    with pytest.raises(ValueError):
        make_station().record_load(0, -1.0)


def test_seed_history_extends_hourly_series():
    station = make_station()
    station.seed_history([10.0, 20.0])
    station.seed_history([30.0])
    assert station.hourly_history == [10.0, 20.0, 30.0]


def test_seed_history_rejects_negative_values():
    with pytest.raises(ValueError):
        make_station().seed_history([10.0, -5.0])


def test_forecast_without_history_is_empty():
    assert make_station().build_forecast() == ()


def test_forecast_with_short_history_is_flat():
    station = make_station()
    station.seed_history([30.0, 50.0])
    assert station.build_forecast(horizon=3) == (40.0, 40.0, 40.0)


def test_forecast_follows_daily_pattern_with_enough_history():
    station = make_station()
    station.seed_history(daily_pattern(7))
    forecast = station.build_forecast()
    expected = 50 + 20 * np.sin(2 * np.pi * (np.arange(24 * 7, 24 * 8) - 6) / 24)
    assert len(forecast) == 24
    assert np.abs(np.array(forecast) - expected).max() < 0.1


def test_forecast_is_limited_by_station_power():
    station = make_station(power=40.0)
    station.seed_history([100.0] * 5)
    assert station.build_forecast(horizon=2) == (40.0, 40.0)


def test_forecast_peak_hours_start_from_current_hour():
    station = make_station()
    station.begin_tick(8)  # 02:00
    forecast = (10.0,) * 24
    forecast = forecast[:5] + (40.0,) + forecast[5:]
    forecast = forecast[:24]
    assert station.forecast_peak_hours(forecast) == (7,)


def test_history_is_collected_across_ticks_and_feeds_forecast():
    station = make_station()
    for tick in range(4 * 4):
        station.record_load(tick, 20.0)
    assert station.hourly_history == [20.0] * 4
    assert station.build_forecast(horizon=2) == (20.0, 20.0)


def test_forecast_is_cached_until_history_changes(monkeypatch):
    from mas import station_agent

    calls = []
    original = station_agent.forecast_load

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(station_agent, "forecast_load", counting)
    station = make_station()
    station.seed_history([10.0] * 5)
    first = station.build_forecast(horizon=3)
    second = station.build_forecast(horizon=3)
    assert first == second
    assert len(calls) == 1


def test_forecast_cache_is_refreshed_with_new_hour():
    station = make_station()
    station.seed_history([10.0] * 5)
    before = station.build_forecast(horizon=2)
    for tick in range(4):
        station.record_load(tick, 50.0)
    after = station.build_forecast(horizon=2)
    assert after != before


def test_forecast_cache_depends_on_horizon():
    station = make_station()
    station.seed_history([10.0] * 5)
    assert len(station.build_forecast(horizon=2)) == 2
    assert len(station.build_forecast(horizon=4)) == 4


def test_forecast_with_temperatures_bypasses_cache():
    station = make_station()
    station.seed_history([10.0] * 5)
    plain = station.build_forecast(horizon=2)
    cold = station.build_forecast(horizon=2, temperatures=[-20.0, -20.0])
    assert cold[0] > plain[0]
    assert station.build_forecast(horizon=2) == plain
import numpy as np
import pytest

from mas import forecast
from mas.forecast import (
    MIN_HISTORY_HOURS,
    forecast_load,
    forecast_temperatures,
    holt_winters_forecast,
    naive_forecast,
    temperature_factor,
)


def daily_pattern(days, noise=0.0, seed=1):
    hours = np.arange(24 * days)
    values = 50 + 20 * np.sin(2 * np.pi * (hours - 6) / 24)
    if noise:
        values = values + np.random.default_rng(seed).normal(0, noise, len(values))
    return values


def test_temperature_factor_cold():
    assert temperature_factor(-20.0) == 1.25
    assert temperature_factor(0.0) == 1.05
    assert temperature_factor(-45.0) == 1.25


def test_temperature_factor_comfortable_range():
    assert temperature_factor(5.0) == 1.05
    assert temperature_factor(20.0) == 1.0
    assert temperature_factor(25.0) == 1.0
    assert temperature_factor(30.0) == 1.0


def test_temperature_factor_heat():
    assert temperature_factor(35.0) == 1.05
    assert temperature_factor(40.0) == 1.1
    assert temperature_factor(50.0) == 1.1


def test_forecast_temperatures_follow_daily_cycle():
    temps = forecast_temperatures(10.0, 5.0, start_hour=4, horizon=3)
    assert list(temps) == [10.0, 11.3, 12.5]
    assert forecast_temperatures(10.0, 5.0, start_hour=10, horizon=1)[0] == 15.0


def test_forecast_temperatures_wrap_after_midnight():
    temps = forecast_temperatures(10.0, 5.0, start_hour=22, horizon=5)
    assert len(temps) == 5
    assert temps[2] == forecast_temperatures(10.0, 5.0, start_hour=0, horizon=1)[0]


def test_naive_forecast_without_history_is_empty():
    assert naive_forecast([], 5) == ()


def test_naive_forecast_short_history_uses_mean():
    assert naive_forecast([10.0, 30.0], 3) == (20.0, 20.0, 20.0)


def test_naive_forecast_repeats_last_day_aligned():
    history = list(range(30))
    assert naive_forecast(history, 3) == (6.0, 7.0, 8.0)
    assert naive_forecast(history, 30)[24] == 6.0


def test_naive_forecast_rejects_bad_horizon():
    with pytest.raises(ValueError):
        naive_forecast([1.0], 0)


def test_holt_winters_requires_enough_history():
    with pytest.raises(ValueError):
        holt_winters_forecast(daily_pattern(2), 24)


def test_holt_winters_reproduces_clean_daily_pattern():
    history = daily_pattern(7)
    expected = 50 + 20 * np.sin(2 * np.pi * (np.arange(24 * 7, 24 * 8) - 6) / 24)
    result = holt_winters_forecast(history, 24)
    assert len(result) == 24
    assert np.abs(result - expected).max() < 0.1


def test_holt_winters_handles_noisy_data():
    history = daily_pattern(7, noise=2.0)
    expected = 50 + 20 * np.sin(2 * np.pi * (np.arange(24 * 7, 24 * 8) - 6) / 24)
    result = holt_winters_forecast(history, 24)
    assert np.abs(result - expected).mean() < 3.0


def test_forecast_load_uses_naive_for_short_history():
    history = [10.0] * 5
    assert forecast_load(history, 3) == (10.0, 10.0, 10.0)


def test_forecast_load_empty_history_gives_empty_forecast():
    assert forecast_load([], 4) == ()


def test_forecast_load_uses_holt_winters_with_enough_history():
    history = daily_pattern(7)
    result = forecast_load(history, 24)
    assert len(result) == 24
    expected = 50 + 20 * np.sin(2 * np.pi * (np.arange(24 * 7, 24 * 8) - 6) / 24)
    assert np.abs(np.array(result) - expected).max() < 0.1


def test_forecast_load_is_clipped_to_station_power():
    history = [100.0] * 5
    assert forecast_load(history, 2, max_power_kw=80.0) == (80.0, 80.0)
    assert forecast_load([-5.0] * 5, 2) == (0.0, 0.0)


def test_forecast_load_applies_temperature_factor():
    result = forecast_load([10.0] * 5, 3, temperatures=[-20.0, 20.0, 45.0])
    assert result == (12.5, 10.0, 11.0)


def test_forecast_load_temperature_length_must_match_horizon():
    with pytest.raises(ValueError):
        forecast_load([10.0] * 5, 3, temperatures=[10.0])


def test_forecast_load_rejects_bad_horizon():
    with pytest.raises(ValueError):
        forecast_load([10.0] * 5, 0)


def test_forecast_load_falls_back_when_model_fails(monkeypatch):
    def broken(history, horizon):
        raise RuntimeError("модель не сошлась")

    monkeypatch.setattr(forecast, "holt_winters_forecast", broken)
    history = list(daily_pattern(4))
    assert len(history) >= MIN_HISTORY_HOURS
    assert forecast_load(history, 6) == tuple(round(v, 3) for v in naive_forecast(history, 6))
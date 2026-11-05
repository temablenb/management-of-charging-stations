import pytest

from mas.tariff import (
    DAY,
    NIGHT,
    PEAK,
    load_multiplier,
    pressure_from_forecast,
    tariff_multiplier,
    time_of_day_factor,
    time_zone,
    zone_of_hour,
)


def test_zone_of_hour_night():
    for hour in (23, 0, 3, 6):
        assert zone_of_hour(hour) == NIGHT


def test_zone_of_hour_peak():
    for hour in (7, 8, 9, 17, 18, 19, 20):
        assert zone_of_hour(hour) == PEAK


def test_zone_of_hour_day():
    for hour in (10, 12, 16, 21, 22):
        assert zone_of_hour(hour) == DAY


def test_zone_of_hour_rejects_invalid_hour():
    with pytest.raises(ValueError):
        zone_of_hour(24)
    with pytest.raises(ValueError):
        zone_of_hour(-1)


def test_time_zone_by_tick():
    assert time_zone(0) == NIGHT   # 00:00
    assert time_zone(28) == PEAK   # 07:00
    assert time_zone(40) == DAY    # 10:00
    assert time_zone(68) == PEAK   # 17:00
    assert time_zone(84) == DAY    # 21:00
    assert time_zone(92) == NIGHT  # 23:00


def test_time_zone_wraps_to_next_day():
    assert time_zone(96) == NIGHT       # 00:00 следующих суток
    assert time_zone(96 + 28) == PEAK   # 07:00 следующих суток


def test_time_of_day_factor_values():
    assert time_of_day_factor(0) == 0.85
    assert time_of_day_factor(48) == 1.0    # 12:00
    assert time_of_day_factor(72) == 1.15   # 18:00


def test_load_multiplier_low_demand():
    assert load_multiplier(0.0, 0.5) == 0.7
    assert load_multiplier(0.15, 0.5) == pytest.approx(0.85, abs=1e-3)


def test_load_multiplier_medium_demand():
    assert load_multiplier(0.3, 0.5) == pytest.approx(1.0, abs=1e-3)
    assert load_multiplier(0.5, 0.5) == pytest.approx(1.15, abs=1e-3)


def test_load_multiplier_high_demand():
    assert load_multiplier(0.7, 0.5) == pytest.approx(1.3, abs=1e-3)
    assert load_multiplier(1.0, 0.5) == pytest.approx(1.6, abs=1e-3)


def test_load_multiplier_network_high():
    assert load_multiplier(0.5, 1.0) == pytest.approx(1.35, abs=1e-3)


def test_load_multiplier_network_low():
    assert load_multiplier(0.5, 0.2) == pytest.approx(1.05, abs=1e-3)


def test_load_multiplier_forecast_and_curtailment():
    assert load_multiplier(0.5, 0.5, forecast_pressure=1.0) == pytest.approx(1.45, abs=1e-3)
    assert load_multiplier(0.5, 0.5, curtailment=0.5) == pytest.approx(1.35, abs=1e-3)


def test_load_multiplier_clamped():
    assert load_multiplier(1.0, 1.0) == 1.6
    assert load_multiplier(0.0, 0.0) == 0.7


def test_load_multiplier_clamps_ratios():
    assert load_multiplier(2.0, 0.5) == load_multiplier(1.0, 0.5)
    assert load_multiplier(-1.0, 0.5) == load_multiplier(0.0, 0.5)
    assert load_multiplier(0.5, 0.5, forecast_pressure=5.0) == load_multiplier(
        0.5, 0.5, forecast_pressure=1.0
    )


def test_load_multiplier_custom_range():
    assert load_multiplier(0.0, 0.5, min_mult=0.5, max_mult=2.0) == 0.5
    assert load_multiplier(1.0, 0.5, min_mult=0.5, max_mult=2.0) == 2.0


def test_load_multiplier_rejects_invalid_range():
    with pytest.raises(ValueError):
        load_multiplier(0.5, 0.5, min_mult=1.6, max_mult=0.7)
    with pytest.raises(ValueError):
        load_multiplier(0.5, 0.5, min_mult=0.0, max_mult=1.6)


def test_pressure_from_forecast_zero_without_forecast_or_below_threshold():
    assert pressure_from_forecast((), 100.0) == 0.0
    assert pressure_from_forecast((50.0, 70.0), 100.0) == 0.0
    assert pressure_from_forecast((90.0,), 0.0) == 0.0


def test_pressure_from_forecast_scales_with_predicted_peak():
    assert pressure_from_forecast((85.0,), 100.0) == pytest.approx(0.5, abs=1e-6)
    assert pressure_from_forecast((20.0, 90.0, 40.0), 100.0) == pytest.approx(2 / 3, abs=1e-6)


def test_pressure_from_forecast_capped_at_one():
    assert pressure_from_forecast((150.0,), 100.0) == 1.0


def test_tariff_multiplier_depends_on_time_of_day():
    night = tariff_multiplier(2, 0.5, 0.5)    # 00:30
    day = tariff_multiplier(48, 0.5, 0.5)     # 12:00
    peak = tariff_multiplier(72, 0.5, 0.5)    # 18:00
    assert night == pytest.approx(0.9775, abs=1e-3)
    assert day == pytest.approx(1.15, abs=1e-3)
    assert peak == pytest.approx(1.3225, abs=1e-3)
    assert night < day < peak


def test_tariff_multiplier_clamped_to_range():
    assert tariff_multiplier(72, 1.0, 1.0) == 1.6
    assert tariff_multiplier(2, 0.0, 0.0) == 0.7
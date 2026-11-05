import pytest

from mas.tariff import DAY, NIGHT, PEAK, time_of_day_factor, time_zone, zone_of_hour


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
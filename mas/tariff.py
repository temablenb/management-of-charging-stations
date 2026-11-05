"""Тарифный множитель: время суток и нагрузка.

Итоговый множитель = множитель нагрузки × коэффициент зоны суток,
результат ограничивается диапазоном [min_mult, max_mult].
"""
from mas.clock import hour_of_tick

NIGHT = "night"
DAY = "day"
PEAK = "peak"

ZONE_FACTORS = {NIGHT: 0.85, DAY: 1.0, PEAK: 1.15}


def zone_of_hour(hour: int) -> str:
    if not 0 <= hour <= 23:
        raise ValueError("Час должен быть от 0 до 23")
    if hour >= 23 or hour < 7:
        return NIGHT
    if 7 <= hour < 10 or 17 <= hour < 21:
        return PEAK
    return DAY


def time_zone(tick: int) -> str:
    return zone_of_hour(hour_of_tick(tick))


def time_of_day_factor(tick: int) -> float:
    return ZONE_FACTORS[time_zone(tick)]
"""Тарифный множитель: время суток и нагрузка.

Итоговый множитель = множитель нагрузки × коэффициент зоны суток,
результат ограничивается диапазоном [min_mult, max_mult].
"""
from mas.clock import hour_of_tick

DEFAULT_MIN_MULT = 0.7
DEFAULT_MAX_MULT = 1.6

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


def _validate_range(min_mult: float, max_mult: float) -> None:
    if not 0 < min_mult < max_mult:
        raise ValueError("Должно выполняться 0 < минимальный множитель < максимальный")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def pressure_from_forecast(forecast_kw: tuple[float, ...], max_power_kw: float) -> float:
    """Давление прогноза на тариф.

    0, пока ожидаемый пик не выше 70% мощности станции, дальше растёт до 1.
    """
    if not forecast_kw or max_power_kw <= 0:
        return 0.0
    predicted_ratio = max(forecast_kw) / max_power_kw
    if predicted_ratio <= 0.70:
        return 0.0
    return min(1.0, (predicted_ratio - 0.70) / 0.30)


def load_multiplier(
    demand_ratio: float,
    network_ratio: float,
    forecast_pressure: float = 0.0,
    curtailment: float = 0.0,
    min_mult: float = DEFAULT_MIN_MULT,
    max_mult: float = DEFAULT_MAX_MULT,
) -> float:
    """Множитель по нагрузке (перенос calc_tariff_mult из optimizer.py).

    demand_ratio: загрузка станции (потребность / мощность);
    network_ratio: загрузка сети (суммарная потребность / доступный лимит);
    forecast_pressure: давление прогноза от 0 до 1;
    curtailment: доля недопоставленной мощности от 0 до 1.
    """
    _validate_range(min_mult, max_mult)
    demand_ratio = _clamp(demand_ratio, 0.0, 1.0)
    forecast_pressure = _clamp(forecast_pressure, 0.0, 1.0)
    curtailment = _clamp(curtailment, 0.0, 1.0)

    if demand_ratio < 0.30:
        value = min_mult + (1.0 - min_mult) * (demand_ratio / 0.30)
    elif demand_ratio < 0.70:
        value = 1.0 + 0.3 * ((demand_ratio - 0.30) / 0.40)
    else:
        value = 1.3 + (max_mult - 1.3) * ((demand_ratio - 0.70) / 0.30)

    if network_ratio > 0.85:
        value += 0.2 * ((network_ratio - 0.85) / 0.15)
    elif network_ratio < 0.30:
        value -= 0.1

    value += forecast_pressure * 0.3
    value += curtailment * 0.4
    return round(_clamp(value, min_mult, max_mult), 3)


def tariff_multiplier(
    tick: int,
    demand_ratio: float,
    network_ratio: float,
    forecast_pressure: float = 0.0,
    curtailment: float = 0.0,
    min_mult: float = DEFAULT_MIN_MULT,
    max_mult: float = DEFAULT_MAX_MULT,
) -> float:
    """Итоговый множитель: нагрузка × зона суток, в пределах [min_mult; max_mult]."""
    base = load_multiplier(
        demand_ratio, network_ratio, forecast_pressure, curtailment, min_mult, max_mult
    )
    return round(_clamp(base * time_of_day_factor(tick), min_mult, max_mult), 3)
"""Прогноз нагрузки станции: метод Хольта–Винтерса и температурный коэффициент.

Ряд почасовой: значение это средняя нагрузка станции за час, кВт.
"""
import numpy as np

SEASON_HOURS = 24
MIN_HISTORY_HOURS = 3 * SEASON_HOURS
DEFAULT_HORIZON = 24
PEAK_FACTOR = 1.3


def temperature_factor(temp_c: float) -> float:
    """Поправка спроса на температуру: на морозе и в жару зарядок больше."""
    if temp_c < 5.0:
        factor = 1.0 + 0.25 * min(1.0, (5.0 - temp_c) / 25.0)
    elif temp_c <= 20.0:
        factor = 1.0 + 0.05 * ((20.0 - temp_c) / 15.0)
    elif temp_c <= 30.0:
        factor = 1.0
    else:
        factor = 1.0 + 0.10 * min(1.0, (temp_c - 30.0) / 10.0)
    return round(factor, 4)


def forecast_temperatures(
    base_temp_c: float, amplitude_c: float, start_hour: int, horizon: int
) -> np.ndarray:
    """Суточный ход температуры (синусоида, минимум около 4 часов) на horizon часов."""
    hours = [(start_hour + step) % 24 for step in range(horizon)]
    return np.array([
        round(base_temp_c + amplitude_c * np.sin(2 * np.pi * (hour - 4) / 24), 1)
        for hour in hours
    ])


def naive_forecast(history, horizon: int = DEFAULT_HORIZON) -> tuple[float, ...]:
    """Простой прогноз: повтор последних суток, при короткой истории среднее, без истории ()."""
    if horizon < 1:
        raise ValueError("Горизонт прогноза должен быть не меньше одного часа")
    values = [float(value) for value in history]
    if not values:
        return ()
    if len(values) >= SEASON_HOURS:
        season = values[-SEASON_HOURS:]
        return tuple(season[index % SEASON_HOURS] for index in range(horizon))
    mean = sum(values) / len(values)
    return tuple(mean for _ in range(horizon))
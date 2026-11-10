"""Прогноз нагрузки станции: метод Хольта–Винтерса и температурный коэффициент.

Ряд почасовой: значение это средняя нагрузка станции за час, кВт.
"""
import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing

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


def holt_winters_forecast(history, horizon: int = DEFAULT_HORIZON) -> np.ndarray:
    """Тройное экспоненциальное сглаживание: уровень, тренд и суточная сезонность."""
    series = np.asarray(history, dtype=float)
    if len(series) < MIN_HISTORY_HOURS:
        raise ValueError(
            f"Для метода Хольта–Винтерса нужно не меньше {MIN_HISTORY_HOURS} часов истории"
        )
    model = ExponentialSmoothing(
        series,
        trend="add",
        seasonal="add",
        seasonal_periods=SEASON_HOURS,
        initialization_method="estimated",
    ).fit(optimized=True, use_brute=False)
    return np.asarray(model.forecast(horizon))


def forecast_load(
    history,
    horizon: int = DEFAULT_HORIZON,
    max_power_kw: float | None = None,
    temperatures=None,
) -> tuple[float, ...]:
    """Прогноз почасовой нагрузки станции на horizon часов, кВт.

    Хольт–Винтерс при достаточной истории, иначе (или при сбое подгонки) простой прогноз.
    Температурная поправка применяется, если переданы temperatures (по числу часов),
    результат ограничивается снизу нулём и сверху мощностью станции.
    """
    if horizon < 1:
        raise ValueError("Горизонт прогноза должен быть не меньше одного часа")
    if len(history) >= MIN_HISTORY_HOURS:
        try:
            values = holt_winters_forecast(history, horizon)
        except Exception:  # подгонка модели может не сойтись, тогда берём простой прогноз
            values = np.asarray(naive_forecast(history, horizon), dtype=float)
    else:
        values = np.asarray(naive_forecast(history, horizon), dtype=float)
    if values.size == 0:
        return ()
    if temperatures is not None:
        if len(temperatures) != horizon:
            raise ValueError("Число температур должно совпадать с горизонтом прогноза")
        values = values * np.array([temperature_factor(t) for t in temperatures])
    upper = np.inf if max_power_kw is None else max_power_kw
    values = np.clip(values, 0.0, upper)
    return tuple(round(float(value), 3) for value in values)


def peak_hours(
    forecast, start_hour: int, factor: float = PEAK_FACTOR
) -> tuple[int, ...]:
    """Часы суток (0–23), в которые прогноз выше среднего в factor раз."""
    if not forecast:
        return ()
    mean = sum(forecast) / len(forecast)
    hours = {
        (start_hour + step) % 24
        for step, value in enumerate(forecast)
        if value > mean * factor
    }
    return tuple(sorted(hours))
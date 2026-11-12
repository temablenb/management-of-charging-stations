"""Генератор потока автомобилей: время приезда по суточному профилю, модели, параметры."""
import numpy as np

from mas.clock import TICKS_PER_DAY, TICKS_PER_HOUR

# Относительная интенсивность приездов по часам суток: ночью мало,
# утренний (7–10) и вечерний (17–21) пики совпадают с пиковыми тарифными зонами.
HOUR_WEIGHTS = (
    0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3,      # 00–06
    2.0, 2.0, 2.0,                           # 07–09 утренний пик
    1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,      # 10–16
    2.5, 2.5, 2.5, 2.5,                      # 17–20 вечерний пик
    0.8, 0.8,                                # 21–22
    0.3,                                     # 23
)


def arrival_probabilities(weights=HOUR_WEIGHTS) -> np.ndarray:
    """Вероятность приезда в каждый час суток (сумма равна 1)."""
    values = np.asarray(weights, dtype=float)
    if values.shape != (24,):
        raise ValueError("Нужно ровно 24 веса, по одному на час суток")
    if (values < 0).any() or values.sum() <= 0:
        raise ValueError("Веса должны быть неотрицательными, хотя бы один положительный")
    return values / values.sum()


def generate_arrival_ticks(
    per_day: int, days: int, rng: np.random.Generator, weights=HOUR_WEIGHTS
) -> list[int]:
    """Такты приезда автомобилей за все сутки сценария в порядке возрастания.

    Каждые сутки приезжает ровно per_day автомобилей, час выбирается по профилю,
    такт внутри часа равновероятно.
    """
    if per_day < 0:
        raise ValueError("Число автомобилей в сутки не может быть отрицательным")
    if days < 1:
        raise ValueError("Сценарий должен длиться хотя бы одни сутки")
    probabilities = arrival_probabilities(weights)
    ticks = []
    for day in range(days):
        hours = rng.choice(24, size=per_day, p=probabilities)
        offsets = rng.integers(0, TICKS_PER_HOUR, size=per_day)
        ticks.extend(
            int(day * TICKS_PER_DAY + hour * TICKS_PER_HOUR + offset)
            for hour, offset in zip(hours, offsets)
        )
    return sorted(ticks)
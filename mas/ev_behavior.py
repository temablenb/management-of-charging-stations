"""Поведение автомобиля: реакция на тариф по времени суток.

Автомобиль знает опубликованное расписание тарифных зон (ночь, день, пик) и, если
дедлайн позволяет, откладывает заявку на более дешёвое время. Нагрузочная часть тарифа
заранее неизвестна, поэтому в расчёт берётся только время суток.
"""
import math

from mas.charging_plan import TICK_HOURS
from mas.tariff import time_of_day_factor

SAFETY_FACTOR = 1.5
MAX_SAVING = 0.3


def min_charge_ticks(energy_kwh: float, max_power_kw: float) -> int:
    """Минимальное число тактов зарядки на максимальной мощности автомобиля."""
    return math.ceil(energy_kwh / (max_power_kw * TICK_HOURS) - 1e-9)


def latest_start_tick(
    energy_kwh: float, max_power_kw: float, deadline_tick: int
) -> int:
    """Самый поздний такт подачи заявки с запасом: станция может дать меньше полной мощности."""
    needed = math.ceil(min_charge_ticks(energy_kwh, max_power_kw) * SAFETY_FACTOR)
    return deadline_tick - needed


def choose_start_tick(
    arrival_tick: int,
    deadline_tick: int,
    energy_kwh: float,
    max_power_kw: float,
    price_sensitivity: float,
) -> int:
    """Такт, в который автомобиль подаёт заявку.

    Если чувствительность к цене нулевая или запаса времени нет, это такт приезда.
    Иначе ищется самый дешёвый по тарифной зоне такт до последнего допустимого;
    сдвиг делается, только если экономия не меньше порога (1 - чувствительность) * 30%.
    """
    if price_sensitivity <= 0:
        return arrival_tick
    latest = latest_start_tick(energy_kwh, max_power_kw, deadline_tick)
    if latest <= arrival_tick:
        return arrival_tick
    base_factor = time_of_day_factor(arrival_tick)
    best_tick, best_factor = arrival_tick, base_factor
    for tick in range(arrival_tick + 1, latest + 1):
        factor = time_of_day_factor(tick)
        if factor < best_factor - 1e-12:
            best_tick, best_factor = tick, factor
    saving = (base_factor - best_factor) / base_factor
    required = (1.0 - price_sensitivity) * MAX_SAVING
    if saving > 0 and saving >= required:
        return best_tick
    return arrival_tick
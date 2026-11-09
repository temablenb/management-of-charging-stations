"""План зарядки: деление мощности станции между автомобилями, расписание, дедлайны.

Единицы измерения: мощность в кВт, энергия в кВт·ч, время в тактах (1 такт = 15 минут).
"""
import math

from mas.charging_queue import Order
from mas.clock import TICK_MINUTES

TICK_HOURS = TICK_MINUTES / 60
PLAN_HORIZON = 96
EPS = 1e-9


def energy_per_tick(power_kw: float) -> float:
    """Сколько энергии (кВт·ч) передаётся за один такт при заданной мощности."""
    return power_kw * TICK_HOURS


def max_useful_power(order: Order) -> float:
    """Больше этой мощности автомобилю не нужно: предел зарядки и остаток энергии за такт."""
    return min(order.max_power_kw, order.remaining_kwh / TICK_HOURS)


def split_power(orders, available_kw: float) -> dict[str, float]:
    """Делит доступную мощность между автомобилями поровну с учётом их пределов.

    Автомобиль, которому поровну достаётся больше его предела, получает свой предел,
    а излишек делится между остальными (равномерное наполнение).
    """
    if available_kw < 0:
        raise ValueError("Доступная мощность не может быть отрицательной")
    limits = {order.ev_id: max_useful_power(order) for order in orders}
    result = {ev_id: 0.0 for ev_id in limits}
    remaining = available_kw
    pending = sorted(limits, key=lambda ev_id: (limits[ev_id], ev_id))
    while pending:
        share = remaining / len(pending)
        ev_id = pending[0]
        if limits[ev_id] <= share + EPS:
            result[ev_id] = limits[ev_id]
            remaining -= limits[ev_id]
            pending.pop(0)
        else:
            rounded = math.floor(share * 1e6) / 1e6
            for ev_id in pending:
                result[ev_id] = rounded
            break
    return result




def ticks_to_finish(remaining_kwh: float, power_kw: float) -> int | None:
    """Сколько тактов нужно до конца зарядки при постоянной мощности.

    0, если энергия уже получена; None, если мощности нет, а энергия ещё нужна.
    """
    if remaining_kwh <= EPS:
        return 0
    if power_kw <= EPS:
        return None
    return math.ceil(remaining_kwh / energy_per_tick(power_kw) - EPS)


def expected_finish_tick(remaining_kwh: float, power_kw: float, tick: int) -> int | None:
    """Номер такта, в начале которого зарядка будет завершена (None, если мощности нет)."""
    ticks = ticks_to_finish(remaining_kwh, power_kw)
    return None if ticks is None else tick + ticks


def build_schedule(
    remaining_kwh: float, power_kw: float, horizon: int = PLAN_HORIZON
) -> tuple[float, ...]:
    """Мощность по тактам: постоянная, в последнем такте ровно столько, сколько осталось."""
    ticks = ticks_to_finish(remaining_kwh, power_kw)
    if not ticks:
        return ()
    last_kw = (remaining_kwh - energy_per_tick(power_kw) * (ticks - 1)) / TICK_HOURS
    schedule = [power_kw] * (ticks - 1) + [min(last_kw, power_kw)]
    return tuple(round(value, 6) for value in schedule[:horizon])


def meets_deadline(finish_tick: int | None, deadline_tick: int) -> bool:
    """Успевает ли зарядка завершиться к дедлайну (завершение в такт дедлайна допустимо)."""
    return finish_tick is not None and finish_tick <= deadline_tick


def slack_ticks(finish_tick: int | None, deadline_tick: int) -> int | None:
    """Запас до дедлайна в тактах (отрицательный, если опаздывает; None без мощности)."""
    return None if finish_tick is None else deadline_tick - finish_tick


def required_power_kw(remaining_kwh: float, tick: int, deadline_tick: int) -> float:
    """Постоянная мощность, нужная чтобы закончить к дедлайну (inf, если время уже вышло)."""
    if remaining_kwh <= EPS:
        return 0.0
    ticks_left = deadline_tick - tick
    if ticks_left <= 0:
        return math.inf
    return remaining_kwh / (ticks_left * TICK_HOURS)
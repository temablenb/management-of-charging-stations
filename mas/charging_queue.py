"""Очередь заявок станции: приоритеты и распределение по местам зарядки."""
from dataclasses import dataclass

from mas.messages import ChargeRequest


PREPAID_BONUS_TICKS = 8


@dataclass
class Order:
    """Заявка автомобиля в очереди станции (изменяемая: убывает remaining_kwh)."""

    ev_id: str
    arrival_tick: int
    energy_kwh: float
    deadline_tick: int
    max_power_kw: float
    prepaid: bool
    remaining_kwh: float
    start_tick: int | None = None

    @classmethod
    def from_request(cls, request: ChargeRequest) -> "Order":
        return cls(
            ev_id=request.sender,
            arrival_tick=request.tick,
            energy_kwh=request.energy_kwh,
            deadline_tick=request.deadline_tick,
            max_power_kw=request.max_power_kw,
            prepaid=request.prepaid,
            remaining_kwh=request.energy_kwh,
        )


def waiting_ticks(order: Order, tick: int) -> int:
    """Сколько тактов заявка ждёт с момента подачи."""
    return max(0, tick - order.arrival_tick)


def priority_score(order: Order, tick: int) -> int:
    """Балл приоритета: время ожидания плюс бонус предоплаты. Чем больше, тем раньше."""
    bonus = PREPAID_BONUS_TICKS if order.prepaid else 0
    return waiting_ticks(order, tick) + bonus
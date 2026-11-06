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


class ChargingQueue:
    """Места зарядки и список ожидания."""

    def __init__(self, slots: int) -> None:
        if slots < 1:
            raise ValueError("На станции должно быть хотя бы одно место")
        self.slots = slots
        self._active: dict[str, Order] = {}
        self._waiting: dict[str, Order] = {}

    def __contains__(self, ev_id: str) -> bool:
        return ev_id in self._active or ev_id in self._waiting

    @property
    def active(self) -> tuple[Order, ...]:
        """Автомобили, которые заряжаются сейчас."""
        return tuple(self._active.values())

    @property
    def free_slots(self) -> int:
        return self.slots - len(self._active)

    @property
    def waiting_count(self) -> int:
        return len(self._waiting)

    def add(self, order: Order) -> None:
        if order.ev_id in self:
            raise ValueError(f"Заявка {order.ev_id} уже в очереди")
        self._waiting[order.ev_id] = order

    def waiting(self, tick: int) -> list[Order]:
        """Ожидающие заявки в порядке приоритета."""
        return sorted(
            self._waiting.values(),
            key=lambda order: (-priority_score(order, tick), order.arrival_tick, order.ev_id),
        )

    def position(self, ev_id: str, tick: int) -> int:
        """0 для заряжающегося автомобиля, 1 для первого в ожидании и так далее."""
        if ev_id in self._active:
            return 0
        for index, order in enumerate(self.waiting(tick), start=1):
            if order.ev_id == ev_id:
                return index
        raise KeyError(ev_id)

    def remove(self, ev_id: str) -> Order:
        if ev_id in self._active:
            return self._active.pop(ev_id)
        if ev_id in self._waiting:
            return self._waiting.pop(ev_id)
        raise KeyError(ev_id)

    def admit(self, tick: int) -> list[Order]:
        """Переводит ожидающих на свободные места по приоритету, возвращает принятых."""
        admitted = []
        for order in self.waiting(tick):
            if self.free_slots <= 0:
                break
            del self._waiting[order.ev_id]
            order.start_tick = tick
            self._active[order.ev_id] = order
            admitted.append(order)
        return admitted
"""Метрики симуляции: состояние сети по тактам и итоги прогона."""
from dataclasses import dataclass

OVERLOAD_TOLERANCE_KW = 1e-3


@dataclass(frozen=True)
class TickRecord:
    """Состояние сети в одном такте (мощность в кВт)."""

    tick: int
    station_kw: dict[str, float]
    charging: dict[str, int]
    waiting: dict[str, int]
    price: dict[str, float]
    storage_charge_kw: float
    storage_discharge_kw: float
    storage_soc: float | None
    limit_kw: float

    @property
    def stations_kw(self) -> float:
        """Суммарная мощность зарядки автомобилей."""
        return sum(self.station_kw.values())

    @property
    def grid_kw(self) -> float:
        """Нагрузка на подстанцию: станции плюс заряд накопителя минус его отдача."""
        return self.stations_kw + self.storage_charge_kw - self.storage_discharge_kw

    @property
    def overload_kw(self) -> float:
        """Превышение лимита подстанции (0, если лимит не превышен)."""
        return max(0.0, self.grid_kw - self.limit_kw)

    @property
    def is_overloaded(self) -> bool:
        return self.overload_kw > OVERLOAD_TOLERANCE_KW


def collect_tick(sim, tick: int) -> TickRecord:
    """Снимает состояние сети; вызывается после распределения мощности, до конца такта."""
    stations = sim.stations
    storage = sim.storage
    return TickRecord(
        tick=tick,
        station_kw={s.agent_id: sum(s.last_powers.values()) for s in stations},
        charging={s.agent_id: len(s.queue.active) for s in stations},
        waiting={s.agent_id: s.queue.waiting_count for s in stations},
        price={s.agent_id: s.price_per_kwh for s in stations},
        storage_charge_kw=storage.charge_kw if storage else 0.0,
        storage_discharge_kw=storage.discharge_kw if storage else 0.0,
        storage_soc=storage.soc if storage else None,
        limit_kw=sim.config.substation_limit_kw,
    )
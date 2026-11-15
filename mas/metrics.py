"""Метрики симуляции: состояние сети по тактам и итоги прогона."""
from dataclasses import dataclass

from mas.charging_plan import TICK_HOURS
from mas.tariff import time_of_day_factor

OVERLOAD_TOLERANCE_KW = 1e-3
PURCHASE_SHARE = 0.6
OVERLOAD_PENALTY_MULT = 3.0


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


@dataclass(frozen=True)
class LoadMetrics:
    """Нагрузка на подстанцию за прогон."""

    peak_load_kw: float
    mean_load_kw: float
    overload_ticks: int
    max_overload_kw: float
    overload_kwh: float


def load_metrics(records) -> LoadMetrics:
    """Пиковая и средняя нагрузка, число тактов с превышением лимита и объём превышения."""
    if not records:
        return LoadMetrics(0.0, 0.0, 0, 0.0, 0.0)
    loads = [record.grid_kw for record in records]
    overloads = [record.overload_kw for record in records if record.is_overloaded]
    return LoadMetrics(
        peak_load_kw=max(loads),
        mean_load_kw=sum(loads) / len(loads),
        overload_ticks=len(overloads),
        max_overload_kw=max(overloads, default=0.0),
        overload_kwh=sum(overloads) * TICK_HOURS,
    )


def cost_metrics(records, base_tariff_rub: float) -> tuple[float, float]:
    """Затраты оператора: закупка энергии у сети и штраф за превышение лимита, руб.

    Закупочная цена равна доле PURCHASE_SHARE от базового тарифа и меняется по тем же
    зонам суток, что и тариф для водителей (ночью дешевле, в пик дороже). Накопитель
    снижает затраты: заряд ночью дешевле отдачи в пик. Превышение лимита штрафуется
    по цене в OVERLOAD_PENALTY_MULT раз выше базовой закупочной.
    """
    purchase_price = base_tariff_rub * PURCHASE_SHARE
    purchase = 0.0
    penalty = 0.0
    for record in records:
        purchase += (
            max(0.0, record.grid_kw) * TICK_HOURS
            * purchase_price * time_of_day_factor(record.tick)
        )
        penalty += (
            record.overload_kw * TICK_HOURS * purchase_price * OVERLOAD_PENALTY_MULT
        )
    return purchase, penalty


def decision_counts(decisions) -> tuple[int, int]:
    """Сколько тактов Grid Agent работал в дефиците и сколько раз перешёл на запасной вариант."""
    deficit = sum(1 for decision in decisions if decision.deficit)
    fallback = sum(1 for decision in decisions if decision.fallback)
    return deficit, fallback
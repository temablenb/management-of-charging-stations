"""Метрики симуляции: состояние сети по тактам и итоги прогона."""
from dataclasses import asdict, dataclass

from mas.charging_plan import TICK_HOURS
from mas.ev_agent import EVState
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


@dataclass(frozen=True)
class VehicleMetrics:
    """Итоги по автомобилям."""

    total: int
    done: int
    deadline_met: int
    missed: int
    no_station: int
    unfinished: int
    avg_wait_ticks: float
    max_wait_ticks: int


def station_orders(station) -> list:
    """Все заявки станции: завершённые, идущие, просроченные и прерванные."""
    return (
        list(station.completed)
        + list(station.queue.active)
        + list(station.queue.waiting(station.current_tick))
        + list(station.expired)
        + list(station.interrupted)
    )


def vehicle_metrics(sim) -> VehicleMetrics:
    """Сколько автомобилей уложилось в дедлайн, сколько опоздало и сколько ждало в очереди."""
    states = [ev.state for ev in sim.evs]
    finished = {EVState.DONE, EVState.MISSED, EVState.NO_STATION}
    waits = [
        order.start_tick - order.arrival_tick
        for station in sim.stations
        for order in station_orders(station)
        if order.start_tick is not None
    ]
    return VehicleMetrics(
        total=len(states),
        done=states.count(EVState.DONE),
        deadline_met=sum(1 for ev in sim.evs if ev.deadline_met),
        missed=states.count(EVState.MISSED),
        no_station=states.count(EVState.NO_STATION),
        unfinished=sum(1 for state in states if state not in finished),
        avg_wait_ticks=sum(waits) / len(waits) if waits else 0.0,
        max_wait_ticks=max(waits, default=0),
    )


@dataclass(frozen=True)
class RunSummary:
    """Итоги прогона для отчёта и сравнения с базовым сценарием."""

    ticks: int
    energy_kwh: float
    revenue_rub: float
    peak_load_kw: float
    mean_load_kw: float
    overload_ticks: int
    max_overload_kw: float
    overload_kwh: float
    deficit_ticks: int
    fallback_ticks: int
    max_waiting: int
    vehicles_total: int
    vehicles_done: int
    deadline_met: int
    missed: int
    no_station: int
    unfinished: int
    avg_wait_ticks: float
    max_wait_ticks: int
    storage_charged_kwh: float
    storage_discharged_kwh: float
    storage_final_soc: float | None
    purchase_cost_rub: float
    overload_penalty_rub: float

    @property
    def operator_cost_rub(self) -> float:
        """Затраты оператора: закупка энергии плюс штраф за превышение лимита."""
        return self.purchase_cost_rub + self.overload_penalty_rub

    @property
    def margin_rub(self) -> float:
        """Выручка от водителей за вычетом затрат оператора."""
        return self.revenue_rub - self.operator_cost_rub

    @property
    def avg_price_rub_per_kwh(self) -> float:
        """Средняя цена зарядки, руб/кВт·ч."""
        return self.revenue_rub / self.energy_kwh if self.energy_kwh > 0 else 0.0

    @property
    def deadline_met_share(self) -> float:
        """Доля автомобилей, получивших нужную энергию к дедлайну."""
        return self.deadline_met / self.vehicles_total if self.vehicles_total else 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["operator_cost_rub"] = self.operator_cost_rub
        data["margin_rub"] = self.margin_rub
        data["avg_price_rub_per_kwh"] = self.avg_price_rub_per_kwh
        data["deadline_met_share"] = self.deadline_met_share
        return data


def summarize(sim) -> RunSummary:
    """Собирает итоги прогона: нагрузка, затраты, автомобили, накопитель."""
    load = load_metrics(sim.records)
    deficit_ticks, fallback_ticks = decision_counts(sim.grid.decisions)
    vehicles = vehicle_metrics(sim)
    storage = sim.storage
    purchase, penalty = cost_metrics(sim.records, sim.config.base_tariff_rub)
    return RunSummary(
        ticks=len(sim.records),
        energy_kwh=sum(station.delivered_kwh for station in sim.stations),
        revenue_rub=sum(station.revenue_rub for station in sim.stations),
        peak_load_kw=load.peak_load_kw,
        mean_load_kw=load.mean_load_kw,
        overload_ticks=load.overload_ticks,
        max_overload_kw=load.max_overload_kw,
        overload_kwh=load.overload_kwh,
        deficit_ticks=deficit_ticks,
        fallback_ticks=fallback_ticks,
        max_waiting=max((sum(record.waiting.values()) for record in sim.records), default=0),
        vehicles_total=vehicles.total,
        vehicles_done=vehicles.done,
        deadline_met=vehicles.deadline_met,
        missed=vehicles.missed,
        no_station=vehicles.no_station,
        unfinished=vehicles.unfinished,
        avg_wait_ticks=vehicles.avg_wait_ticks,
        max_wait_ticks=vehicles.max_wait_ticks,
        storage_charged_kwh=storage.charged_kwh if storage else 0.0,
        storage_discharged_kwh=storage.discharged_kwh if storage else 0.0,
        storage_final_soc=storage.soc if storage else None,
        purchase_cost_rub=purchase,
        overload_penalty_rub=penalty,
    )
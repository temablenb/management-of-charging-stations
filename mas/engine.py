"""Движок имитационной модели: собирает агентов сценария и прогоняет их по тактам."""
import numpy as np

from mas.bus import MessageBus
from mas.clock import TICKS_PER_DAY, SimulationClock
from mas.ev_agent import EVAgent, EVProfile, StationInfo
from mas.ev_generator import vehicle_rng
from mas.grid_agent import GridAgent
from mas.history import warmup_history
from mas.scenario import ScenarioConfig
from mas.station_agent import StationAgent
from mas.storage_agent import StorageAgent

DEFAULT_WARMUP_DAYS = 3


class Simulation:
    """Мультиагентная симуляция сети зарядных станций."""

    def __init__(
        self,
        config: ScenarioConfig,
        profiles: list[EVProfile],
        warmup_days: int = DEFAULT_WARMUP_DAYS,
    ) -> None:
        self.config = config
        self.profiles = list(profiles)
        self.bus = MessageBus()
        self.clock = SimulationClock()
        self.grid = GridAgent(
            self.bus,
            limit_kw=config.substation_limit_kw,
            tariff_min_mult=config.tariff_min_mult,
            tariff_max_mult=config.tariff_max_mult,
        )
        self.stations = [
            StationAgent(self.bus, station_config, base_tariff_rub=config.base_tariff_rub)
            for station_config in config.stations
        ]
        self.storage = StorageAgent(self.bus, config.storage) if config.storage else None
        infos = tuple(
            StationInfo(item.station_id, item.connector, item.max_power_kw)
            for item in config.stations
        )
        self.evs = [
            EVAgent(self.bus, profile, infos, vehicle_rng(config.seed, profile.ev_id))
            for profile in self.profiles
        ]
        warmup_rng = np.random.default_rng([config.seed, 7])
        for station in self.stations:
            station.seed_history(
                warmup_history(config, station.config, warmup_days, warmup_rng)
            )

    @property
    def total_ticks(self) -> int:
        return self.config.days * TICKS_PER_DAY

    @property
    def tick(self) -> int:
        return self.clock.tick

    @property
    def finished(self) -> bool:
        return self.clock.tick >= self.total_ticks

    def step(self) -> int:
        """Выполняет один такт и возвращает его номер.

        Порядок фаз: инициатива агентов и заявки, запросы станций, решение Grid Agent,
        выделение и планы, обработка планов автомобилями, конец такта.
        """
        if self.finished:
            raise RuntimeError("Симуляция уже завершена")
        tick = self.clock.tick
        self.grid.begin_tick(tick)
        if self.storage:
            self.storage.begin_tick(tick)
        for station in self.stations:
            station.begin_tick(tick)
        for ev in self.evs:
            ev.begin_tick(tick)
        self.bus.deliver()
        for station in self.stations:
            station.process_inbox()
        for station in self.stations:
            station.send_power_request()
        self.bus.deliver()
        self.grid.process_inbox()
        self.grid.run_allocation()
        self.bus.deliver()
        for station in self.stations:
            station.process_inbox()
        if self.storage:
            self.storage.process_inbox()
        self.bus.deliver()
        for ev in self.evs:
            ev.process_inbox()
        for station in self.stations:
            station.end_tick(tick)
        if self.storage:
            self.storage.end_tick(tick)
        self.clock.advance()
        return tick

    def finalize(self) -> None:
        """Доставляет последние сообщения (отчёты о завершении зарядки) автомобилям."""
        self.bus.deliver()
        for ev in self.evs:
            ev.process_inbox()

    def run(self, ticks: int | None = None) -> None:
        """Выполняет ticks тактов (по умолчанию до конца сценария), затем finalize()."""
        remaining = self.total_ticks - self.clock.tick
        count = remaining if ticks is None else min(ticks, remaining)
        if count < 0:
            raise ValueError("Число тактов не может быть отрицательным")
        for _ in range(count):
            self.step()
        self.finalize()
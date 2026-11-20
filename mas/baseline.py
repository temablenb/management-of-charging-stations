"""Базовый сценарий для сравнения: сеть без координации агентов.

Отличия от мультиагентной системы:
- Grid Agent не ограничивает мощность: каждая станция получает всё, что запросила
  (в пределах своей мощности), лимит подстанции только измеряется;
- тариф фиксированный (множитель 1,0);
- очередь на станциях строго по порядку приезда, предоплата ничего не даёт;
- накопителя нет;
- автомобили не откладывают заявки в поисках дешёвого времени суток.
Автомобили и их выбор станций те же, что в мультиагентном прогоне.
"""
from dataclasses import replace

from mas.allocation import EPS, AllocationResult
from mas.engine import Simulation
from mas.ev_agent import EVProfile
from mas.grid_agent import GridAgent
from mas.scenario import ScenarioConfig
from mas.station_agent import StationAgent
from mas.storage_agent import StorageAgent


class UnlimitedGridAgent(GridAgent):
    """Grid Agent без контроля нагрузки и с плоским тарифом."""

    def compute_allocation(self) -> AllocationResult:
        caps = {
            station: min(request.demand_kw, request.max_power_kw)
            for station, request in self._requests.items()
        }
        deficit = sum(caps.values()) > self.effective_limit_kw + EPS
        return AllocationResult(caps, deficit=deficit)

    def compute_multipliers(self, result: AllocationResult) -> dict[str, float]:
        return {station: 1.0 for station in self._requests}


class BaselineSimulation(Simulation):
    """Симуляция базового сценария на тех же автомобилях и том же движке."""

    def __init__(self, config: ScenarioConfig, profiles: list[EVProfile]) -> None:
        super().__init__(replace(config, storage=None), profiles, warmup_days=0)

    def _create_grid(self) -> GridAgent:
        return UnlimitedGridAgent(self.bus, limit_kw=self.config.substation_limit_kw)

    def _create_stations(self) -> list[StationAgent]:
        return [
            StationAgent(
                self.bus, item, base_tariff_rub=self.config.base_tariff_rub, fifo=True
            )
            for item in self.config.stations
        ]

    def _create_storage(self) -> StorageAgent | None:
        return None

    def _vehicle_profile(self, profile: EVProfile) -> EVProfile:
        return replace(profile, price_sensitivity=0.0)

    def _seed_history(self, warmup_days: int) -> None:
        """Прогноз базовому сценарию не нужен, предыстория не создаётся."""
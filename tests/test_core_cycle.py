import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.grid_agent import GRID_ID, GridAgent
from mas.messages import MessageType, PowerAllocation, PowerRequest


def constant(value):
    return lambda tick: value


class FakeStation(BaseAgent):
    """Станция-заглушка: в начале такта просит заданную мощность, выделение запоминает."""

    def __init__(self, agent_id, bus, demand_fn, max_power_kw=100.0):
        super().__init__(agent_id, bus)
        self.demand_fn = demand_fn
        self.max_power_kw = max_power_kw
        self.allocations = []

    def begin_tick(self, tick):
        self.send(PowerRequest(
            sender=self.agent_id, receiver=GRID_ID, tick=tick,
            demand_kw=self.demand_fn(tick), max_power_kw=self.max_power_kw,
            forecast_kw=(),
        ))

    def handle(self, message):
        if isinstance(message, PowerAllocation):
            self.allocations.append(message)
        else:
            super().handle(message)


def make_network(demand_fns, limit_kw=150.0):
    bus = MessageBus()
    grid = GridAgent(bus, limit_kw=limit_kw)
    stations = [
        FakeStation(f"st-{index}", bus, fn)
        for index, fn in enumerate(demand_fns, start=1)
    ]
    return bus, grid, stations


def run_tick(bus, grid, stations, tick):
    grid.begin_tick(tick)
    for station in stations:
        station.begin_tick(tick)
    bus.deliver()
    grid.process_inbox()
    grid.run_allocation()
    bus.deliver()
    for station in stations:
        station.process_inbox()


def test_tick_round_trip_with_deficit():
    bus, grid, stations = make_network([constant(50.0), constant(60.0), constant(70.0)])
    run_tick(bus, grid, stations, tick=10)
    total = 0.0
    for station, demand in zip(stations, (50.0, 60.0, 70.0)):
        (allocation,) = station.allocations
        assert allocation.tick == 10
        assert 0.6 * demand - 1e-6 <= allocation.allocated_kw <= demand + 1e-6
        total += allocation.allocated_kw
    assert total == pytest.approx(150.0, abs=1e-4)


def test_total_allocation_never_exceeds_limit_over_day():
    demand_fns = [
        (lambda tick, shift=shift: 40.0 + 15.0 * ((tick + shift) % 5))
        for shift in range(3)
    ]
    bus, grid, stations = make_network(demand_fns)
    for tick in range(24):
        run_tick(bus, grid, stations, tick)
    for index in range(24):
        total = sum(station.allocations[index].allocated_kw for station in stations)
        assert total <= 150.0 + 1e-4
    assert bus.count_by_type() == {
        MessageType.POWER_REQUEST: 72,
        MessageType.POWER_ALLOCATION: 72,
    }
    assert len(grid.decisions) == 24


def test_tariff_multiplier_follows_time_of_day():
    bus, grid, stations = make_network([constant(50.0), constant(50.0)])
    for tick in (2, 48, 72):  # 00:30, 12:00, 18:00
        run_tick(bus, grid, stations, tick)
    night, day, peak = (a.tariff_multiplier for a in stations[0].allocations)
    assert night == pytest.approx(0.9775, abs=1e-3)
    assert day == pytest.approx(1.15, abs=1e-3)
    assert peak == pytest.approx(1.3225, abs=1e-3)


def run_ticks(count):
    bus, grid, stations = make_network(
        [constant(60.0), constant(80.0), lambda tick: 30.0 + 5.0 * (tick % 6)]
    )
    for tick in range(count):
        run_tick(bus, grid, stations, tick)
    return [
        (a.tick, a.allocated_kw, a.tariff_multiplier)
        for station in stations
        for a in station.allocations
    ]


def test_same_input_gives_identical_results():
    assert run_ticks(12) == run_ticks(12)
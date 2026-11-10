import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.grid_agent import GridAgent
from mas.messages import ChargeComplete, ChargePlan, ChargeRequest, MessageType
from mas.scenario import StationConfig
from mas.station_agent import StationAgent


class FakeEV(BaseAgent):
    """Автомобиль-заглушка: запоминает полученные планы и отчёты о завершении."""

    def __init__(self, ev_id, bus):
        super().__init__(ev_id, bus)
        self.plans = []
        self.reports = []

    def handle(self, message):
        if isinstance(message, ChargePlan):
            self.plans.append(message)
        elif isinstance(message, ChargeComplete):
            self.reports.append(message)
        else:
            super().handle(message)


def make_network(limit_kw=120.0, station_powers=(100.0, 100.0), slots=5):
    bus = MessageBus()
    grid = GridAgent(bus, limit_kw=limit_kw)
    stations = [
        StationAgent(bus, StationConfig(f"st-{i}", power, "CCS", slots=slots))
        for i, power in enumerate(station_powers, start=1)
    ]
    return bus, grid, stations


def run_tick(bus, grid, stations, evs, tick, requests=()):
    """Один такт: тот же порядок фаз, что будет в движке симуляции."""
    grid.begin_tick(tick)
    for station in stations:
        station.begin_tick(tick)
    for ev, request in requests:
        ev.send(request)
    bus.deliver()
    for station in stations:
        station.process_inbox()
    for station in stations:
        station.send_power_request()
    bus.deliver()
    grid.process_inbox()
    grid.run_allocation()
    bus.deliver()
    for station in stations:
        station.process_inbox()
    bus.deliver()
    for ev in evs:
        ev.process_inbox()
    for station in stations:
        station.end_tick(tick)


def request(ev, station_id, tick, energy=40.0, max_power=100.0, deadline=40):
    return ev, ChargeRequest(
        sender=ev.agent_id, receiver=station_id, tick=tick,
        energy_kwh=energy, deadline_tick=deadline,
        max_power_kw=max_power, connector="CCS", prepaid=False,
    )


def test_two_stations_share_substation_limit():
    bus, grid, stations = make_network(limit_kw=120.0)
    ev1, ev2 = FakeEV("ev-1", bus), FakeEV("ev-2", bus)
    run_tick(bus, grid, stations, [ev1, ev2], 0, [
        request(ev1, "st-1", 0), request(ev2, "st-2", 0),
    ])
    (decision,) = grid.decisions
    assert decision.deficit
    assert decision.total_allocated_kw <= 120.0 + 1e-4
    assert ev1.plans[0].schedule_kw[0] == pytest.approx(60.0)
    assert ev2.plans[0].schedule_kw[0] == pytest.approx(60.0)
    assert ev1.plans[0].expected_finish_tick == 3


def test_vehicles_get_full_energy_over_several_ticks():
    bus, grid, stations = make_network(limit_kw=120.0)
    ev1, ev2 = FakeEV("ev-1", bus), FakeEV("ev-2", bus)
    evs = [ev1, ev2]
    run_tick(bus, grid, stations, evs, 0, [
        request(ev1, "st-1", 0), request(ev2, "st-2", 0),
    ])
    for tick in range(1, 6):
        run_tick(bus, grid, stations, evs, tick)
    for station in stations:
        assert station.delivered_kwh == pytest.approx(40.0)
        assert len(station.completed) == 1
        assert station.completed[0].finish_tick == 3
    assert all(not station.queue.active for station in stations)


def test_total_allocation_never_exceeds_limit_over_many_ticks():
    bus, grid, stations = make_network(limit_kw=150.0, station_powers=(100.0, 90.0, 80.0))
    evs = [FakeEV(f"ev-{i}", bus) for i in range(1, 7)]
    arrivals = {0: [0, 1, 2], 2: [3, 4, 5]}
    for tick in range(12):
        requests = [
            request(evs[i], f"st-{i % 3 + 1}", tick, energy=30.0, deadline=tick + 30)
            for i in arrivals.get(tick, [])
        ]
        run_tick(bus, grid, stations, evs, tick, requests)
    assert all(d.total_allocated_kw <= 150.0 + 1e-4 for d in grid.decisions)
    assert len(grid.decisions) == 12
    assert sum(s.delivered_kwh for s in stations) == pytest.approx(6 * 30.0)


def test_tariff_multiplier_reaches_station_and_grows_in_peak():
    bus, grid, stations = make_network(limit_kw=120.0)
    ev1 = FakeEV("ev-1", bus)
    run_tick(bus, grid, stations, [ev1], 2, [request(ev1, "st-1", 2, energy=400.0, deadline=200)])
    night = stations[0].tariff_multiplier
    run_tick(bus, grid, stations, [ev1], 72)
    peak = stations[0].tariff_multiplier
    assert peak > night


def test_message_counts_per_tick():
    bus, grid, stations = make_network()
    ev1 = FakeEV("ev-1", bus)
    run_tick(bus, grid, stations, [ev1], 0, [request(ev1, "st-1", 0)])
    counts = bus.count_by_type()
    assert counts[MessageType.CHARGE_REQUEST] == 1
    assert counts[MessageType.POWER_REQUEST] == 2
    assert counts[MessageType.POWER_ALLOCATION] == 2
    assert counts[MessageType.CHARGE_PLAN] == 1


def test_deactivated_station_gets_no_power():
    bus, grid, stations = make_network(limit_kw=200.0)
    ev1, ev2 = FakeEV("ev-1", bus), FakeEV("ev-2", bus)
    run_tick(bus, grid, stations, [ev1, ev2], 0, [
        request(ev1, "st-1", 0), request(ev2, "st-2", 0),
    ])
    stations[0].set_active(False)
    run_tick(bus, grid, stations, [ev1, ev2], 1)
    assert grid.decisions[-1].allocated_kw["st-1"] == 0.0
    assert grid.decisions[-1].allocated_kw["st-2"] > 0.0


def test_deadline_expires_order_in_network():
    bus, grid, stations = make_network(limit_kw=20.0, station_powers=(100.0,))
    ev1 = FakeEV("ev-1", bus)
    run_tick(bus, grid, stations, [ev1], 0, [
        request(ev1, "st-1", 0, energy=100.0, max_power=100.0, deadline=3),
    ])
    for tick in range(1, 4):
        run_tick(bus, grid, stations, [ev1], tick)
    assert [order.ev_id for order in stations[0].expired] == ["ev-1"]
    assert stations[0].completed == []
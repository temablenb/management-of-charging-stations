import numpy as np
import pytest

from mas.bus import MessageBus
from mas.ev_agent import EVAgent, EVProfile, EVState, StationInfo
from mas.grid_agent import GridAgent
from mas.messages import MessageType
from mas.scenario import StationConfig
from mas.station_agent import StationAgent


def make_network(limit_kw=120.0, powers=(100.0, 100.0), connectors=("CCS", "CCS")):
    bus = MessageBus()
    grid = GridAgent(bus, limit_kw=limit_kw)
    configs = [
        StationConfig(f"st-{i}", power, connector)
        for i, (power, connector) in enumerate(zip(powers, connectors), start=1)
    ]
    stations = [StationAgent(bus, config) for config in configs]
    infos = tuple(StationInfo(c.station_id, c.connector, c.max_power_kw) for c in configs)
    return bus, grid, stations, infos


def make_ev(bus, infos, ev_id, seed=0, **overrides):
    params = dict(
        ev_id=ev_id, battery_kwh=60.0, soc=0.2, target_soc=0.8,
        max_charge_kw=100.0, connector="CCS", arrival_tick=0, deadline_tick=40,
    )
    params.update(overrides)
    return EVAgent(bus, EVProfile(**params), infos, np.random.default_rng(seed))


def run_tick(bus, grid, stations, evs, tick):
    """Один такт: тот же порядок фаз, что будет в движке симуляции."""
    grid.begin_tick(tick)
    for station in stations:
        station.begin_tick(tick)
    for ev in evs:
        ev.begin_tick(tick)
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


def run(bus, grid, stations, evs, ticks):
    for tick in range(ticks):
        run_tick(bus, grid, stations, evs, tick)


def test_vehicle_charges_and_gets_report():
    bus, grid, stations, infos = make_network(powers=(100.0,), connectors=("CCS",))
    ev = make_ev(bus, infos, "ev-1")
    run(bus, grid, stations, [ev], 8)
    assert ev.state == EVState.DONE
    assert ev.deadline_met
    assert ev.delivered_kwh == pytest.approx(36.0)
    assert ev.soc == pytest.approx(0.8)
    assert ev.cost_rub > 0
    assert ev.finish_tick == 2


def test_vehicles_share_limited_power_and_all_finish():
    bus, grid, stations, infos = make_network(limit_kw=120.0)
    evs = [make_ev(bus, infos, f"ev-{i}", seed=i) for i in range(1, 5)]
    run(bus, grid, stations, evs, 20)
    assert all(ev.deadline_met for ev in evs)
    assert sum(station.delivered_kwh for station in stations) == pytest.approx(4 * 36.0)
    assert all(d.total_allocated_kw <= 120.0 + 1e-4 for d in grid.decisions)


def test_vehicle_waits_in_queue_when_slots_are_full():
    bus, grid, stations, infos = make_network(powers=(100.0,), connectors=("CCS",))
    evs = [make_ev(bus, infos, f"ev-{i}", seed=i) for i in range(1, 8)]
    run_tick(bus, grid, stations, evs, 0)
    states = [ev.state for ev in evs]
    assert states.count(EVState.CHARGING) == 5
    assert states.count(EVState.QUEUED) == 2


def test_waiting_vehicle_eventually_charges():
    bus, grid, stations, infos = make_network(powers=(100.0,), connectors=("CCS",))
    evs = [make_ev(bus, infos, f"ev-{i}", seed=i, deadline_tick=80) for i in range(1, 8)]
    run(bus, grid, stations, evs, 40)
    assert all(ev.state == EVState.DONE for ev in evs)


def test_vehicle_misses_deadline_when_power_is_too_low():
    bus, grid, stations, infos = make_network(limit_kw=10.0, powers=(100.0,), connectors=("CCS",))
    ev = make_ev(bus, infos, "ev-1", deadline_tick=6)
    run(bus, grid, stations, [ev], 10)
    assert ev.state == EVState.MISSED
    assert not ev.deadline_met
    assert [order.ev_id for order in stations[0].expired] == ["ev-1"]


def test_vehicle_without_compatible_station_is_marked():
    bus, grid, stations, infos = make_network(connectors=("CCS", "CCS"))
    ev = make_ev(bus, infos, "ev-1", connector="GB/T")
    run(bus, grid, stations, [ev], 3)
    assert ev.state == EVState.NO_STATION


def test_late_vehicle_starts_when_it_arrives():
    bus, grid, stations, infos = make_network(powers=(100.0,), connectors=("CCS",))
    ev = make_ev(bus, infos, "ev-1", arrival_tick=5, deadline_tick=40)
    run(bus, grid, stations, [ev], 4)
    assert ev.state == EVState.PENDING
    for tick in range(4, 14):
        run_tick(bus, grid, stations, [ev], tick)
    assert ev.state == EVState.DONE
    assert ev.request_tick == 5


def test_cost_matches_price_times_energy_per_tick():
    bus, grid, stations, infos = make_network(powers=(100.0,), connectors=("CCS",))
    ev = make_ev(bus, infos, "ev-1")
    run(bus, grid, stations, [ev], 8)
    (order,) = stations[0].completed
    assert ev.cost_rub == pytest.approx(order.cost_rub)
    average_price = ev.cost_rub / ev.delivered_kwh
    assert 7.0 <= average_price <= 16.0


def test_message_flow_contains_all_types():
    bus, grid, stations, infos = make_network(powers=(100.0,), connectors=("CCS",))
    ev = make_ev(bus, infos, "ev-1")
    run(bus, grid, stations, [ev], 6)
    counts = bus.count_by_type()
    for message_type in (
        MessageType.CHARGE_REQUEST,
        MessageType.POWER_REQUEST,
        MessageType.POWER_ALLOCATION,
        MessageType.CHARGE_PLAN,
        MessageType.CHARGE_COMPLETE,
    ):
        assert counts[message_type] >= 1
    assert counts[MessageType.CHARGE_COMPLETE] == 1
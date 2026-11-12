import numpy as np
import pytest

from mas.bus import MessageBus
from mas.ev_agent import EVAgent, EVProfile, StationInfo
from mas.grid_agent import GridAgent
from mas.scenario import StationConfig, StorageConfig
from mas.station_agent import StationAgent
from mas.storage_agent import StorageAgent


def make_network(with_storage, limit_kw=120.0, soc=0.5):
    bus = MessageBus()
    grid = GridAgent(bus, limit_kw=limit_kw)
    configs = [StationConfig(f"st-{i}", 100.0, "CCS") for i in (1, 2)]
    stations = [StationAgent(bus, config) for config in configs]
    storage = StorageAgent(bus, StorageConfig(200.0, 60.0, 0.92, soc)) if with_storage else None
    infos = tuple(StationInfo(c.station_id, c.connector, c.max_power_kw) for c in configs)
    return bus, grid, stations, storage, infos


def make_ev(bus, infos, ev_id, arrival, seed=0):
    profile = EVProfile(
        ev_id=ev_id, battery_kwh=60.0, soc=0.2, target_soc=0.8, max_charge_kw=100.0,
        connector="CCS", arrival_tick=arrival, deadline_tick=arrival + 40,
    )
    return EVAgent(bus, profile, infos, np.random.default_rng(seed))


def run_tick(bus, grid, stations, storage, evs, tick):
    """Один такт со всеми фазами, включая накопитель."""
    grid.begin_tick(tick)
    if storage:
        storage.begin_tick(tick)
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
    if storage:
        storage.process_inbox()
    bus.deliver()
    for ev in evs:
        ev.process_inbox()
    for station in stations:
        station.end_tick(tick)
    if storage:
        storage.end_tick(tick)


def test_storage_charges_at_night_up_to_limit():
    bus, grid, stations, storage, infos = make_network(True, soc=0.2)
    for tick in range(0, 20):
        run_tick(bus, grid, stations, storage, [], tick)
    assert storage.soc == pytest.approx(0.95, abs=0.01)
    assert storage.charged_kwh > 0
    assert storage.discharged_kwh == 0


def test_storage_does_not_charge_in_daytime():
    bus, grid, stations, storage, infos = make_network(True, soc=0.5)
    for tick in range(44, 52):  # 11:00-13:00
        run_tick(bus, grid, stations, storage, [], tick)
    assert storage.soc == pytest.approx(0.5)


def test_storage_covers_peak_deficit():
    delivered = {}
    for with_storage in (False, True):
        bus, grid, stations, storage, infos = make_network(with_storage, limit_kw=120.0)
        evs = [make_ev(bus, infos, "ev-1", 72, seed=1), make_ev(bus, infos, "ev-2", 72, seed=2)]
        for tick in range(72, 74):
            run_tick(bus, grid, stations, storage, evs, tick)
        delivered[with_storage] = sum(station.delivered_kwh for station in stations)
    assert delivered[False] == pytest.approx(60.0)
    assert delivered[True] == pytest.approx(72.0)


def test_storage_discharge_lowers_soc_during_deficit_only():
    bus, grid, stations, storage, infos = make_network(True, limit_kw=300.0)
    evs = [make_ev(bus, infos, "ev-1", 72)]
    for tick in range(72, 76):
        run_tick(bus, grid, stations, storage, evs, tick)
    assert storage.discharged_kwh == 0
    assert storage.soc == pytest.approx(0.5)


def test_grid_load_with_storage_stays_within_substation_limit():
    bus, grid, stations, storage, infos = make_network(True, limit_kw=120.0)
    evs = [make_ev(bus, infos, "ev-1", 72, seed=1), make_ev(bus, infos, "ev-2", 72, seed=2)]
    for tick in range(72, 80):
        run_tick(bus, grid, stations, storage, evs, tick)
    for decision in grid.decisions:
        net = decision.total_allocated_kw - decision.storage_used_kw
        assert net <= 120.0 + 1e-4
    assert storage.soc_history[0] >= storage.soc_history[-1]


def test_soc_history_has_one_entry_per_tick():
    bus, grid, stations, storage, infos = make_network(True)
    for tick in range(10):
        run_tick(bus, grid, stations, storage, [], tick)
    assert len(storage.soc_history) == 10
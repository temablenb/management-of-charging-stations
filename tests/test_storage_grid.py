import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.grid_agent import GridAgent
from mas.messages import MessageType, PowerRequest, StorageDispatch
from mas.scenario import StorageConfig
from mas.storage_agent import StorageAgent


def make_network(limit_kw=100.0, soc=0.5):
    bus = MessageBus()
    grid = GridAgent(bus, limit_kw=limit_kw)
    stations = {sid: BaseAgent(sid, bus) for sid in ("st-1", "st-2")}
    storage = StorageAgent(bus, StorageConfig(200.0, 60.0, 0.9, soc))
    return bus, grid, stations, storage


def request(sender, demand, tick):
    return PowerRequest(
        sender=sender, receiver="grid", tick=tick,
        demand_kw=demand, max_power_kw=100.0, forecast_kw=(),
    )


def run_peak_tick(bus, grid, stations, storage, demands, tick=72):
    grid.begin_tick(tick)
    storage.begin_tick(tick)
    for sid, demand in demands.items():
        stations[sid].send(request(sid, demand, tick))
    bus.deliver()
    grid.process_inbox()
    grid.run_allocation()
    bus.deliver()
    storage.process_inbox()


def test_dispatch_message_type_and_validation():
    message = StorageDispatch(sender="grid", receiver="storage", tick=1, discharge_kw=10.0)
    assert message.type == MessageType.STORAGE_DISPATCH
    with pytest.raises(ValueError):
        StorageDispatch(sender="grid", receiver="storage", tick=1, discharge_kw=-1.0)


def test_grid_sends_dispatch_with_used_reserve():
    bus, grid, stations, storage = make_network(limit_kw=100.0)
    run_peak_tick(bus, grid, stations, storage, {"st-1": 80.0, "st-2": 80.0})
    assert grid.decisions[-1].total_allocated_kw == pytest.approx(160.0)
    assert grid.decisions[-1].storage_used_kw == pytest.approx(60.0)
    assert storage.discharge_kw == pytest.approx(60.0)


def test_storage_is_not_used_without_deficit():
    bus, grid, stations, storage = make_network(limit_kw=200.0)
    run_peak_tick(bus, grid, stations, storage, {"st-1": 50.0, "st-2": 50.0})
    assert storage.discharge_kw == 0.0
    assert storage.soc == pytest.approx(0.5)


def test_partial_reserve_use_matches_deficit():
    bus, grid, stations, storage = make_network(limit_kw=100.0)
    run_peak_tick(bus, grid, stations, storage, {"st-1": 70.0, "st-2": 70.0})
    assert storage.discharge_kw == pytest.approx(40.0)


def test_no_dispatch_without_offer():
    bus, grid, stations, storage = make_network()
    grid.begin_tick(48)
    stations["st-1"].send(request("st-1", 50.0, 48))
    bus.deliver()
    grid.process_inbox()
    grid.run_allocation()
    bus.deliver()
    assert all(m.type != MessageType.STORAGE_DISPATCH for m in bus.receive("storage"))


def test_night_charging_goes_through_grid_allocation():
    bus, grid, stations, storage = make_network(limit_kw=100.0)
    grid.begin_tick(2)
    storage.begin_tick(2)
    stations["st-1"].send(request("st-1", 30.0, 2))
    bus.deliver()
    grid.process_inbox()
    grid.run_allocation()
    bus.deliver()
    storage.process_inbox()
    assert storage.charge_kw == pytest.approx(60.0)
    assert grid.decisions[-1].total_allocated_kw == pytest.approx(90.0)


def test_night_charging_is_cut_when_substation_is_busy():
    bus, grid, stations, storage = make_network(limit_kw=100.0)
    grid.begin_tick(2)
    storage.begin_tick(2)
    stations["st-1"].send(request("st-1", 90.0, 2))
    bus.deliver()
    grid.process_inbox()
    grid.run_allocation()
    bus.deliver()
    storage.process_inbox()
    assert grid.decisions[-1].total_allocated_kw <= 100.0 + 1e-4
    assert storage.charge_kw < 60.0
import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.grid_agent import GridAgent
from mas.messages import ChargeRequest, PowerRequest


def make_power_request(sender, tick=1, demand_kw=50.0, max_power_kw=100.0):
    return PowerRequest(
        sender=sender, receiver="grid", tick=tick,
        demand_kw=demand_kw, max_power_kw=max_power_kw, forecast_kw=(),
    )


@pytest.fixture
def setup():
    bus = MessageBus()
    grid = GridAgent(bus, limit_kw=100.0)
    stations = {sid: BaseAgent(sid, bus) for sid in ("st-1", "st-2")}
    return bus, grid, stations


def run_requests(bus, grid, stations, demands, tick=1):
    grid.begin_tick(tick)
    for station_id, demand in demands.items():
        stations[station_id].send(make_power_request(station_id, tick, demand))
    bus.deliver()
    grid.process_inbox()


def test_grid_agent_registers_with_default_id(setup):
    bus, _, _ = setup
    assert bus.is_registered("grid")


def test_non_positive_limit_rejected():
    with pytest.raises(ValueError):
        GridAgent(MessageBus(), limit_kw=0)


def test_min_share_out_of_range_rejected():
    with pytest.raises(ValueError):
        GridAgent(MessageBus(), limit_kw=100.0, min_share=1.5)


def test_invalid_limit_does_not_register_agent():
    bus = MessageBus()
    with pytest.raises(ValueError):
        GridAgent(bus, limit_kw=-1)
    assert not bus.is_registered("grid")


def test_requests_collected_from_stations(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 30.0, "st-2": 40.0})
    assert set(grid.requests) == {"st-1", "st-2"}


def test_begin_tick_clears_requests(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 30.0})
    grid.begin_tick(2)
    assert grid.requests == {}
    assert grid.current_tick == 2


def test_last_request_from_station_wins(setup):
    bus, grid, stations = setup
    grid.begin_tick(1)
    stations["st-1"].send(make_power_request("st-1", demand_kw=30.0))
    stations["st-1"].send(make_power_request("st-1", demand_kw=60.0))
    bus.deliver()
    grid.process_inbox()
    assert grid.requests["st-1"].demand_kw == 60.0


def test_request_from_other_tick_rejected(setup):
    bus, grid, stations = setup
    grid.begin_tick(2)
    stations["st-1"].send(make_power_request("st-1", tick=1))
    bus.deliver()
    with pytest.raises(ValueError):
        grid.process_inbox()


def test_unexpected_message_type_rejected(setup):
    bus, grid, _ = setup
    ev = BaseAgent("ev-1", bus)
    ev.send(ChargeRequest(
        sender="ev-1", receiver="grid", tick=1,
        energy_kwh=20.0, deadline_tick=11,
        max_power_kw=50.0, connector="CCS", prepaid=False,
    ))
    bus.deliver()
    with pytest.raises(NotImplementedError):
        grid.process_inbox()


def test_compute_allocation_without_deficit(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 30.0, "st-2": 40.0})
    result = grid.compute_allocation()
    assert result.allocated_kw == {"st-1": 30.0, "st-2": 40.0}
    assert not result.deficit


def test_compute_allocation_with_deficit(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 80.0, "st-2": 80.0})
    result = grid.compute_allocation()
    assert result.deficit
    assert result.total_kw == pytest.approx(100.0)
    assert all(48.0 - 1e-6 <= power <= 52.0 + 1e-6 for power in result.allocated_kw.values())


def test_compute_allocation_without_requests(setup):
    _, grid, _ = setup
    grid.begin_tick(1)
    assert grid.compute_allocation().allocated_kw == {}


def test_infeasible_allocation_falls_back_to_proportional(setup):
    bus, grid, stations = setup
    # гарантированные минимумы 60 + 60 = 120 кВт больше лимита 100 кВт
    run_requests(bus, grid, stations, {"st-1": 100.0, "st-2": 100.0})
    result = grid.compute_allocation()
    assert result.fallback
    assert result.total_kw == pytest.approx(100.0, abs=1e-5)
    assert result.allocated_kw["st-1"] == pytest.approx(50.0, abs=1e-5)


def test_regular_allocation_is_not_fallback(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 80.0, "st-2": 80.0})
    assert not grid.compute_allocation().fallback
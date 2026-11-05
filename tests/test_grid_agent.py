import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.grid_agent import GridAgent
from mas.messages import ChargeRequest, MessageType, PowerRequest, StorageOffer
from mas.allocation import AllocationResult


def make_power_request(
    sender, tick=1, demand_kw=50.0, max_power_kw=100.0, priority=1.0, forecast_kw=()
):
    return PowerRequest(
        sender=sender, receiver="grid", tick=tick,
        demand_kw=demand_kw, max_power_kw=max_power_kw, forecast_kw=forecast_kw,
        priority=priority,
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


def test_higher_priority_station_gets_more_power(setup):
    bus, grid, stations = setup
    grid.begin_tick(1)
    stations["st-1"].send(make_power_request("st-1", demand_kw=80.0, priority=2.0))
    stations["st-2"].send(make_power_request("st-2", demand_kw=80.0, priority=1.0))
    bus.deliver()
    grid.process_inbox()
    result = grid.compute_allocation()
    assert result.allocated_kw["st-1"] == pytest.approx(52.0, abs=1e-5)
    assert result.allocated_kw["st-2"] == pytest.approx(48.0, abs=1e-5)


@pytest.fixture
def storage(setup):
    bus, _, _ = setup
    return BaseAgent("storage", bus)


def make_offer(tick=1, available_kw=20.0):
    return StorageOffer(
        sender="storage", receiver="grid", tick=tick,
        available_kw=available_kw, soc=0.5,
    )


def test_storage_offer_extends_effective_limit(setup, storage):
    bus, grid, _ = setup
    grid.begin_tick(1)
    storage.send(make_offer(available_kw=20.0))
    bus.deliver()
    grid.process_inbox()
    assert grid.storage_kw == 20.0
    assert grid.effective_limit_kw == 120.0


def test_without_offer_limit_is_substation_limit(setup):
    _, grid, _ = setup
    grid.begin_tick(1)
    assert grid.storage_kw == 0.0
    assert grid.effective_limit_kw == 100.0


def test_begin_tick_clears_storage_offer(setup, storage):
    bus, grid, _ = setup
    grid.begin_tick(1)
    storage.send(make_offer())
    bus.deliver()
    grid.process_inbox()
    grid.begin_tick(2)
    assert grid.storage_kw == 0.0


def test_storage_offer_from_other_tick_rejected(setup, storage):
    bus, grid, _ = setup
    grid.begin_tick(2)
    storage.send(make_offer(tick=1))
    bus.deliver()
    with pytest.raises(ValueError):
        grid.process_inbox()


def test_storage_reserve_removes_deficit(setup, storage):
    bus, grid, stations = setup
    grid.begin_tick(1)
    stations["st-1"].send(make_power_request("st-1", demand_kw=80.0))
    stations["st-2"].send(make_power_request("st-2", demand_kw=80.0))
    storage.send(make_offer(available_kw=60.0))
    bus.deliver()
    grid.process_inbox()
    result = grid.compute_allocation()
    assert not result.deficit
    assert result.allocated_kw == {"st-1": 80.0, "st-2": 80.0}


def test_run_allocation_sends_power_to_stations(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 30.0, "st-2": 40.0})
    grid.run_allocation()
    bus.deliver()
    expected = (("st-1", 30.0, 0.85), ("st-2", 40.0, 0.91375))
    for station_id, expected_kw, expected_multiplier in expected:
        (message,) = bus.receive(station_id)
        assert message.type == MessageType.POWER_ALLOCATION
        assert message.sender == "grid"
        assert message.tick == 1
        assert message.allocated_kw == expected_kw
        assert message.tariff_multiplier == pytest.approx(expected_multiplier, abs=1e-3)


def test_custom_multipliers_are_sent(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 30.0, "st-2": 40.0})
    grid.send_allocations(grid.compute_allocation(), {"st-1": 1.3})
    bus.deliver()
    assert bus.receive("st-1")[0].tariff_multiplier == 1.3
    assert bus.receive("st-2")[0].tariff_multiplier == 1.0


def test_allocation_sent_only_to_requesting_stations(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 30.0})
    grid.run_allocation()
    bus.deliver()
    assert len(bus.receive("st-1")) == 1
    assert bus.receive("st-2") == []


def test_run_allocation_returns_computed_result(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 30.0})
    assert grid.run_allocation().allocated_kw == {"st-1": 30.0}


def test_non_positive_tariff_range_rejected():
    with pytest.raises(ValueError):
        GridAgent(MessageBus(), limit_kw=100.0, tariff_min_mult=1.6, tariff_max_mult=0.7)


def test_multipliers_grow_with_station_load(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 20.0, "st-2": 70.0}, tick=48)
    multipliers = grid.compute_multipliers(grid.compute_allocation())
    assert multipliers["st-1"] == pytest.approx(0.967, abs=1e-3)
    assert multipliers["st-2"] == pytest.approx(1.367, abs=1e-3)


def test_multiplier_is_higher_in_peak_than_at_night(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 40.0}, tick=2)
    night = grid.compute_multipliers(grid.compute_allocation())["st-1"]
    run_requests(bus, grid, stations, {"st-1": 40.0}, tick=72)
    peak = grid.compute_multipliers(grid.compute_allocation())["st-1"]
    assert peak > night


def test_curtailment_raises_multiplier(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 40.0, "st-2": 40.0}, tick=48)
    full = grid.compute_multipliers(AllocationResult({"st-1": 40.0, "st-2": 40.0}, False))
    cut = grid.compute_multipliers(AllocationResult({"st-1": 20.0, "st-2": 20.0}, True))
    assert full["st-1"] == pytest.approx(1.075, abs=1e-3)
    assert cut["st-1"] == pytest.approx(1.275, abs=1e-3)


def test_forecast_pressure_raises_multiplier(setup):
    bus, grid, stations = setup
    grid.begin_tick(48)
    stations["st-1"].send(
        make_power_request("st-1", tick=48, demand_kw=40.0, forecast_kw=(90.0,))
    )
    stations["st-2"].send(make_power_request("st-2", tick=48, demand_kw=40.0))
    bus.deliver()
    grid.process_inbox()
    multipliers = grid.compute_multipliers(grid.compute_allocation())
    assert multipliers["st-1"] - multipliers["st-2"] == pytest.approx(0.2, abs=2e-3)


def test_decisions_empty_initially(setup):
    _, grid, _ = setup
    assert grid.decisions == ()


def test_run_allocation_records_decision(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 30.0, "st-2": 40.0})
    grid.run_allocation()
    (decision,) = grid.decisions
    assert decision.tick == 1
    assert decision.requested_kw == 70.0
    assert decision.total_allocated_kw == 70.0
    assert decision.allocated_kw == {"st-1": 30.0, "st-2": 40.0}
    assert set(decision.multipliers) == {"st-1", "st-2"}
    assert not decision.deficit
    assert not decision.fallback
    assert decision.storage_used_kw == 0.0


def test_decision_records_storage_usage(setup, storage):
    bus, grid, stations = setup
    grid.begin_tick(1)
    stations["st-1"].send(make_power_request("st-1", demand_kw=80.0))
    stations["st-2"].send(make_power_request("st-2", demand_kw=80.0))
    storage.send(make_offer(available_kw=60.0))
    bus.deliver()
    grid.process_inbox()
    grid.run_allocation()
    decision = grid.decisions[0]
    assert decision.storage_kw == 60.0
    assert decision.total_allocated_kw == 160.0
    assert decision.storage_used_kw == pytest.approx(60.0)


def test_decision_records_fallback(setup):
    bus, grid, stations = setup
    run_requests(bus, grid, stations, {"st-1": 100.0, "st-2": 100.0})
    grid.run_allocation()
    decision = grid.decisions[0]
    assert decision.deficit
    assert decision.fallback


def test_decisions_accumulate_across_ticks(setup):
    bus, grid, stations = setup
    for tick in (1, 2, 3):
        run_requests(bus, grid, stations, {"st-1": 30.0}, tick=tick)
        grid.run_allocation()
    assert [decision.tick for decision in grid.decisions] == [1, 2, 3]


def test_decision_without_requests_is_empty(setup):
    _, grid, _ = setup
    grid.begin_tick(5)
    grid.run_allocation()
    (decision,) = grid.decisions
    assert decision.requested_kw == 0.0
    assert decision.allocated_kw == {}
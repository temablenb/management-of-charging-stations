import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.messages import ChargePlan, ChargeRequest, PowerAllocation
from mas.scenario import StationConfig
from mas.station_agent import REJECT_INACTIVE, StationAgent


def make_request(sender, tick=1, energy=40.0, max_power=50.0, deadline=None):
    return ChargeRequest(
        sender=sender, receiver="st-1", tick=tick,
        energy_kwh=energy, deadline_tick=deadline or tick + 40,
        max_power_kw=max_power, connector="CCS", prepaid=False,
    )


def make_setup(slots=2, power=100.0):
    bus = MessageBus()
    grid = BaseAgent("grid", bus)
    station = StationAgent(bus, StationConfig("st-1", power, "CCS", slots=slots))
    evs = {ev_id: BaseAgent(ev_id, bus) for ev_id in ("ev-1", "ev-2", "ev-3")}
    return bus, grid, station, evs


def load(bus, station, evs, requests, tick=1):
    station.begin_tick(tick)
    for request in requests:
        evs[request.sender].send(request)
    bus.deliver()
    station.process_inbox()


def allocate_from_grid(bus, grid, station, kw, multiplier=1.0, tick=None):
    grid.send(PowerAllocation(
        sender="grid", receiver="st-1", tick=station.current_tick if tick is None else tick,
        allocated_kw=kw, tariff_multiplier=multiplier,
    ))
    bus.deliver()
    station.process_inbox()
    bus.deliver()


def test_allocation_sets_multiplier_and_sends_plans():
    bus, grid, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1"), make_request("ev-2")])
    allocate_from_grid(bus, grid, station, 60.0, multiplier=1.2)
    assert station.tariff_multiplier == 1.2
    assert station.price_per_kwh == pytest.approx(12.0)
    assert station.last_powers == {"ev-1": 30.0, "ev-2": 30.0}
    (plan,) = bus.receive("ev-1")
    assert isinstance(plan, ChargePlan)
    assert plan.schedule_kw[0] == 30.0


def test_allocation_from_other_tick_is_rejected():
    bus, grid, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", tick=2)], tick=2)
    grid.send(PowerAllocation(
        sender="grid", receiver="st-1", tick=1, allocated_kw=10.0, tariff_multiplier=1.0,
    ))
    bus.deliver()
    with pytest.raises(ValueError):
        station.process_inbox()


def test_begin_tick_resets_last_powers():
    bus, grid, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1")])
    station.allocate(40.0)
    station.begin_tick(2)
    assert station.last_powers == {}


def test_end_tick_charges_and_records_load():
    bus, grid, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=40.0)])
    allocate_from_grid(bus, grid, station, 40.0)
    station.end_tick(1)
    assert station.queue.active[0].remaining_kwh == pytest.approx(30.0)
    assert station.delivered_kwh == pytest.approx(10.0)
    assert station.last_powers == {}


def test_end_tick_bills_at_current_price():
    bus, grid, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=40.0)])
    allocate_from_grid(bus, grid, station, 40.0, multiplier=1.5)
    station.end_tick(1)
    assert station.queue.active[0].cost_rub == pytest.approx(150.0)


def test_end_tick_without_allocation_does_not_charge():
    bus, grid, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=40.0)])
    station.end_tick(1)
    assert station.delivered_kwh == 0.0
    assert station.queue.active[0].remaining_kwh == 40.0


def test_hourly_history_is_filled_by_end_tick():
    bus, grid, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", tick=0, energy=400.0)], tick=0)
    for tick in range(4):
        if tick:
            station.begin_tick(tick)
        station.allocate(40.0)
        station.end_tick(tick)
    assert station.hourly_history == [40.0]


def test_expired_order_leaves_queue_at_deadline():
    bus, grid, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", tick=1, deadline=5)])
    station.begin_tick(4)
    assert station.expired == []
    station.begin_tick(5)
    assert [order.ev_id for order in station.expired] == ["ev-1"]
    assert "ev-1" not in station.queue


def test_expiry_also_applies_to_waiting_orders():
    bus, grid, station, evs = make_setup(slots=1)
    load(bus, station, evs, [
        make_request("ev-1", tick=1, deadline=30),
        make_request("ev-2", tick=1, deadline=5),
    ])
    assert station.queue.waiting_count == 1
    station.begin_tick(5)
    assert [order.ev_id for order in station.expired] == ["ev-2"]
    assert station.queue.waiting_count == 0
    assert "ev-1" in station.queue


def test_deactivation_interrupts_all_orders():
    bus, grid, station, evs = make_setup(slots=1)
    load(bus, station, evs, [make_request("ev-1"), make_request("ev-2")])
    dropped = station.set_active(False)
    assert {order.ev_id for order in dropped} == {"ev-1", "ev-2"}
    assert station.interrupted == dropped
    assert station.queue.active == ()
    assert station.queue.waiting_count == 0
    assert not station.active


def test_inactive_station_rejects_requests():
    bus, grid, station, evs = make_setup()
    station.set_active(False)
    load(bus, station, evs, [make_request("ev-1")])
    assert station.rejected == [("ev-1", REJECT_INACTIVE)]
    assert "ev-1" not in station.queue


def test_inactive_station_has_zero_demand():
    bus, grid, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1")])
    station.set_active(False)
    assert station.demand_kw() == 0.0


def test_inactive_station_does_not_admit_waiting_orders():
    bus, grid, station, evs = make_setup()
    station.set_active(False)
    station.begin_tick(2)
    assert station.queue.active == ()


def test_reactivation_accepts_requests_again():
    bus, grid, station, evs = make_setup()
    station.set_active(False)
    assert station.set_active(True) == []
    load(bus, station, evs, [make_request("ev-1")])
    assert "ev-1" in station.queue


def test_set_active_is_idempotent():
    _, _, station, _ = make_setup()
    assert station.set_active(True) == []
    assert station.interrupted == []
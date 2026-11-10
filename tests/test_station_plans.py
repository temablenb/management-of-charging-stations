import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.messages import ChargePlan, ChargeRequest, MessageType
from mas.scenario import StationConfig
from mas.station_agent import StationAgent


def make_request(sender, tick=1, energy=20.0, max_power=50.0, prepaid=False):
    return ChargeRequest(
        sender=sender, receiver="st-1", tick=tick,
        energy_kwh=energy, deadline_tick=tick + 40,
        max_power_kw=max_power, connector="CCS", prepaid=prepaid,
    )


def make_setup(slots=2, station_power=100.0):
    bus = MessageBus()
    station = StationAgent(bus, StationConfig("st-1", station_power, "CCS", slots=slots))
    evs = {ev_id: BaseAgent(ev_id, bus) for ev_id in ("ev-1", "ev-2", "ev-3")}
    return bus, station, evs


def load(bus, station, evs, requests, tick=1):
    station.begin_tick(tick)
    for request in requests:
        evs[request.sender].send(request)
    bus.deliver()
    station.process_inbox()


def test_allocate_splits_power_between_active_orders():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1"), make_request("ev-2")])
    assert station.allocate(60.0) == {"ev-1": 30.0, "ev-2": 30.0}
    assert station.last_powers == {"ev-1": 30.0, "ev-2": 30.0}


def test_allocate_is_limited_by_station_power():
    bus, station, evs = make_setup(station_power=40.0)
    load(bus, station, evs, [make_request("ev-1"), make_request("ev-2")])
    assert station.allocate(200.0) == {"ev-1": 20.0, "ev-2": 20.0}


def test_make_plans_for_charging_orders_has_schedule():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=20.0)])
    (plan,) = station.make_plans(40.0)
    assert plan.receiver == "ev-1"
    assert plan.tick == 1
    assert plan.queue_position == 0
    assert plan.schedule_kw == (40.0, 40.0)
    assert plan.expected_finish_tick == 3


def test_make_plans_for_waiting_orders_has_no_schedule():
    bus, station, evs = make_setup(slots=1)
    load(bus, station, evs, [make_request("ev-1"), make_request("ev-2")])
    plans = {plan.receiver: plan for plan in station.make_plans(40.0)}
    assert plans["ev-1"].queue_position == 0
    assert plans["ev-2"].queue_position == 1
    assert plans["ev-2"].schedule_kw == ()
    assert plans["ev-2"].expected_finish_tick is None


def test_make_plans_without_power_has_no_finish():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1")])
    (plan,) = station.make_plans(0.0)
    assert plan.schedule_kw == ()
    assert plan.expected_finish_tick is None


def test_send_plans_delivers_messages_to_evs():
    bus, station, evs = make_setup(slots=1)
    load(bus, station, evs, [make_request("ev-1"), make_request("ev-2")])
    station.send_plans(40.0)
    bus.deliver()
    (first,) = bus.receive("ev-1")
    (second,) = bus.receive("ev-2")
    assert isinstance(first, ChargePlan) and first.type == MessageType.CHARGE_PLAN
    assert first.queue_position == 0
    assert second.queue_position == 1


def test_advance_delivers_energy_for_one_tick():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=20.0)])
    station.allocate(40.0)
    assert station.advance() == []
    (order,) = station.queue.active
    assert order.remaining_kwh == pytest.approx(10.0)
    assert station.delivered_kwh == pytest.approx(10.0)


def test_advance_completes_order_and_frees_slot():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=10.0)])
    station.allocate(40.0)
    (done,) = station.advance()
    assert done.ev_id == "ev-1"
    assert done.remaining_kwh == 0.0
    assert done.finish_tick == 2
    assert station.queue.active == ()
    assert station.completed == [done]


def test_advance_accrues_cost():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=20.0)])
    station.allocate(40.0)
    station.advance(price_per_kwh=12.0)
    (order,) = station.queue.active
    assert order.cost_rub == pytest.approx(120.0)


def test_advance_never_delivers_more_than_remaining():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=5.0)])
    station.advance({"ev-1": 100.0})
    assert station.delivered_kwh == pytest.approx(5.0)


def test_advance_with_zero_power_changes_nothing():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=20.0)])
    assert station.advance({}) == []
    assert station.queue.active[0].remaining_kwh == 20.0
    assert station.delivered_kwh == 0.0


def test_full_charge_takes_expected_number_of_ticks():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=20.0)])
    ticks = 0
    while station.queue.active:
        station.allocate(30.0)
        station.advance()
        ticks += 1
    assert ticks == 3
    assert station.delivered_kwh == pytest.approx(20.0)
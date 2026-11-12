import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.messages import ChargeRequest, StorageOffer
from mas.scenario import StationConfig
from mas.station_agent import REJECT_CONNECTOR, REJECT_DUPLICATE, StationAgent


def make_request(sender, tick=1, connector="CCS", prepaid=False, energy=20.0):
    return ChargeRequest(
        sender=sender, receiver="st-1", tick=tick,
        energy_kwh=energy, deadline_tick=tick + 20,
        max_power_kw=50.0, connector=connector, prepaid=prepaid,
    )


def make_setup(slots=2):
    bus = MessageBus()
    station = StationAgent(bus, StationConfig("st-1", 100.0, "CCS", slots=slots))
    evs = {ev_id: BaseAgent(ev_id, bus) for ev_id in ("ev-1", "ev-2", "ev-3")}
    return bus, station, evs


def deliver_requests(bus, station, evs, requests, tick=1):
    station.begin_tick(tick)
    for request in requests:
        evs[request.sender].send(request)
    bus.deliver()
    station.process_inbox()


@pytest.fixture
def setup():
    return make_setup()


def test_station_registers_with_station_id(setup):
    bus, _, _ = setup
    assert bus.is_registered("st-1")


def test_station_exposes_config(setup):
    _, station, _ = setup
    assert station.max_power_kw == 100.0
    assert station.connector == "CCS"


def test_request_starts_charging_when_slot_is_free(setup):
    bus, station, evs = setup
    deliver_requests(bus, station, evs, [make_request("ev-1")])
    assert station.queue.position("ev-1", 1) == 0
    assert station.queue.free_slots == 1


def test_order_fields_are_copied_from_request(setup):
    bus, station, evs = setup
    deliver_requests(bus, station, evs, [make_request("ev-1", energy=25.0)])
    (order,) = station.queue.active
    assert order.ev_id == "ev-1"
    assert order.arrival_tick == 1
    assert order.energy_kwh == 25.0
    assert order.remaining_kwh == 25.0
    assert order.deadline_tick == 21
    assert order.start_tick == 1


def test_requests_above_slot_count_wait(setup):
    bus, station, evs = setup
    requests = [make_request(ev_id) for ev_id in ("ev-1", "ev-2", "ev-3")]
    deliver_requests(bus, station, evs, requests)
    assert station.queue.waiting_count == 1
    assert station.queue.free_slots == 0
    assert station.queue.position("ev-3", 1) == 1


def test_prepaid_request_is_admitted_first():
    bus, station, evs = make_setup(slots=1)
    deliver_requests(
        bus, station, evs,
        [make_request("ev-1"), make_request("ev-2", prepaid=True)],
    )
    assert [order.ev_id for order in station.queue.active] == ["ev-2"]


def test_connector_mismatch_is_rejected(setup):
    bus, station, evs = setup
    deliver_requests(bus, station, evs, [make_request("ev-1", connector="GB/T")])
    assert station.rejected == [("ev-1", REJECT_CONNECTOR)]
    assert "ev-1" not in station.queue


def test_duplicate_request_is_rejected(setup):
    bus, station, evs = setup
    deliver_requests(bus, station, evs, [make_request("ev-1"), make_request("ev-1")])
    assert station.rejected == [("ev-1", REJECT_DUPLICATE)]
    assert len(station.queue.active) == 1


def test_request_from_other_tick_is_rejected(setup):
    bus, station, evs = setup
    station.begin_tick(2)
    evs["ev-1"].send(make_request("ev-1", tick=1))
    bus.deliver()
    with pytest.raises(ValueError):
        station.process_inbox()


def test_unexpected_message_type_is_rejected(setup):
    bus, station, _ = setup
    grid = BaseAgent("grid", bus)
    grid.send(StorageOffer(
        sender="grid", receiver="st-1", tick=1,
        available_kw=10.0, soc=0.5,
    ))
    bus.deliver()
    with pytest.raises(NotImplementedError):
        station.process_inbox()


def test_begin_tick_admits_waiting_after_slot_freed(setup):
    bus, station, evs = setup
    requests = [make_request(ev_id) for ev_id in ("ev-1", "ev-2", "ev-3")]
    deliver_requests(bus, station, evs, requests)
    station.queue.remove("ev-1")
    station.begin_tick(2)
    assert station.queue.waiting_count == 0
    assert {order.ev_id for order in station.queue.active} == {"ev-2", "ev-3"}
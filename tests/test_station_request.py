import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.messages import ChargeRequest, MessageType
from mas.scenario import StationConfig
from mas.station_agent import StationAgent


def make_request(sender, tick=1, energy=40.0, max_power=50.0):
    return ChargeRequest(
        sender=sender, receiver="st-1", tick=tick,
        energy_kwh=energy, deadline_tick=tick + 40,
        max_power_kw=max_power, connector="CCS", prepaid=False,
    )


def make_setup(slots=2, power=100.0, **kwargs):
    bus = MessageBus()
    BaseAgent("grid", bus)
    station = StationAgent(bus, StationConfig("st-1", power, "CCS", slots=slots), **kwargs)
    evs = {ev_id: BaseAgent(ev_id, bus) for ev_id in ("ev-1", "ev-2", "ev-3", "ev-4")}
    return bus, station, evs


def load(bus, station, evs, requests, tick=1):
    station.begin_tick(tick)
    for request in requests:
        evs[request.sender].send(request)
    bus.deliver()
    station.process_inbox()


def test_non_positive_base_tariff_rejected():
    with pytest.raises(ValueError):
        StationAgent(MessageBus(), StationConfig("st-1", 100.0, "CCS"), base_tariff_rub=0)


def test_price_is_base_tariff_times_multiplier():
    _, station, _ = make_setup(base_tariff_rub=10.0)
    assert station.price_per_kwh == 10.0
    station.tariff_multiplier = 1.3
    assert station.price_per_kwh == pytest.approx(13.0)


def test_priority_without_queue_is_one():
    _, station, _ = make_setup()
    assert station.station_priority() == 1.0


def test_priority_grows_with_waiting_orders():
    bus, station, evs = make_setup(slots=2)
    load(bus, station, evs, [make_request(f"ev-{i}") for i in (1, 2, 3)])
    assert station.queue.waiting_count == 1
    assert station.station_priority() == 1.5


def test_priority_is_capped_at_two():
    bus, station, evs = make_setup(slots=1)
    load(bus, station, evs, [make_request(f"ev-{i}") for i in (1, 2, 3, 4)])
    assert station.queue.waiting_count == 3
    assert station.station_priority() == 2.0


def test_demand_is_zero_without_orders():
    _, station, _ = make_setup()
    assert station.demand_kw() == 0.0


def test_demand_sums_useful_powers():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", max_power=30.0), make_request("ev-2", max_power=40.0)])
    assert station.demand_kw() == 70.0


def test_demand_is_capped_by_station_power():
    bus, station, evs = make_setup(power=60.0)
    load(bus, station, evs, [make_request("ev-1"), make_request("ev-2")])
    assert station.demand_kw() == 60.0


def test_demand_is_limited_by_remaining_energy():
    bus, station, evs = make_setup()
    load(bus, station, evs, [make_request("ev-1", energy=5.0)])
    assert station.demand_kw() == 20.0


def test_send_power_request_message_fields():
    bus, station, evs = make_setup(slots=2)
    load(bus, station, evs, [make_request("ev-1", max_power=30.0)])
    station.seed_history([20.0, 40.0])
    request = station.send_power_request(forecast_horizon=3)
    assert request.type == MessageType.POWER_REQUEST
    assert request.sender == "st-1"
    assert request.receiver == "grid"
    assert request.tick == 1
    assert request.demand_kw == 30.0
    assert request.max_power_kw == 100.0
    assert request.forecast_kw == (30.0, 30.0, 30.0)
    assert request.priority == 1.0


def test_send_power_request_goes_through_bus():
    bus, station, _ = make_setup()
    station.begin_tick(1)
    station.send_power_request()
    bus.deliver()
    (message,) = bus.receive("grid")
    assert message.demand_kw == 0.0
    assert message.forecast_kw == ()
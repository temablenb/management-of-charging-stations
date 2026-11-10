import numpy as np
import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.ev_agent import EVAgent, EVProfile, EVState, StationInfo, choose_station
from mas.messages import MessageType

STATIONS = (
    StationInfo("st-1", "CCS", 100.0),
    StationInfo("st-2", "GB/T", 90.0),
    StationInfo("st-3", "CCS", 80.0),
)


def make_profile(**overrides):
    params = dict(
        ev_id="ev-1", battery_kwh=60.0, soc=0.2, target_soc=0.8,
        max_charge_kw=50.0, connector="CCS", arrival_tick=5, deadline_tick=45,
    )
    params.update(overrides)
    return EVProfile(**params)


def make_ev(profile=None, stations=STATIONS, seed=0):
    bus = MessageBus()
    for info in stations:
        BaseAgent(info.station_id, bus)
    ev = EVAgent(bus, profile or make_profile(), stations, np.random.default_rng(seed))
    return bus, ev


def test_profile_needed_energy():
    assert make_profile().needed_kwh == pytest.approx(36.0)


def test_profile_rejects_invalid_battery():
    with pytest.raises(ValueError):
        make_profile(battery_kwh=0)


def test_profile_rejects_soc_not_below_target():
    with pytest.raises(ValueError):
        make_profile(soc=0.8, target_soc=0.8)
    with pytest.raises(ValueError):
        make_profile(soc=-0.1)
    with pytest.raises(ValueError):
        make_profile(target_soc=1.2)


def test_profile_rejects_invalid_power():
    with pytest.raises(ValueError):
        make_profile(max_charge_kw=0)


def test_profile_rejects_invalid_times():
    with pytest.raises(ValueError):
        make_profile(arrival_tick=-1)
    with pytest.raises(ValueError):
        make_profile(arrival_tick=10, deadline_tick=10)


def test_choose_station_only_compatible_connector():
    rng = np.random.default_rng(0)
    for _ in range(20):
        assert choose_station(STATIONS, "CCS", rng).station_id in ("st-1", "st-3")
    assert choose_station(STATIONS, "GB/T", rng).station_id == "st-2"


def test_choose_station_none_without_compatible():
    assert choose_station(STATIONS, "CHAdeMO", np.random.default_rng(0)) is None


def test_choose_station_is_reproducible_by_seed():
    first = choose_station(STATIONS, "CCS", np.random.default_rng(7))
    second = choose_station(STATIONS, "CCS", np.random.default_rng(7))
    assert first == second


def test_choose_station_does_not_depend_on_input_order():
    shuffled = tuple(reversed(STATIONS))
    for seed in range(5):
        assert (
            choose_station(STATIONS, "CCS", np.random.default_rng(seed))
            == choose_station(shuffled, "CCS", np.random.default_rng(seed))
        )


def test_agent_starts_pending():
    _, ev = make_ev()
    assert ev.state == EVState.PENDING
    assert not ev.finished
    assert not ev.deadline_met
    assert ev.soc == 0.2


def test_no_request_before_arrival():
    bus, ev = make_ev()
    ev.begin_tick(4)
    assert ev.state == EVState.PENDING
    assert bus.pending_count == 0


def test_request_sent_at_arrival():
    bus, ev = make_ev()
    ev.begin_tick(5)
    assert ev.state == EVState.REQUESTED
    assert ev.request_tick == 5
    bus.deliver()
    receiver = ev.station_id
    (request,) = bus.receive(receiver)
    assert request.type == MessageType.CHARGE_REQUEST
    assert request.sender == "ev-1"
    assert request.tick == 5
    assert request.energy_kwh == pytest.approx(36.0)
    assert request.deadline_tick == 45
    assert request.max_power_kw == 50.0
    assert request.connector == "CCS"
    assert receiver in ("st-1", "st-3")


def test_request_is_sent_only_once():
    bus, ev = make_ev()
    ev.begin_tick(5)
    ev.begin_tick(6)
    assert bus.pending_count == 1


def test_no_station_with_matching_connector():
    bus, ev = make_ev(make_profile(connector="CHAdeMO"))
    ev.begin_tick(5)
    assert ev.state == EVState.NO_STATION
    assert ev.finished
    assert bus.pending_count == 0


def test_late_arrival_is_missed_without_request():
    bus, ev = make_ev(make_profile(arrival_tick=5, deadline_tick=10))
    ev.begin_tick(10)
    assert ev.state == EVState.MISSED
    assert bus.pending_count == 0


def test_pending_after_deadline_is_missed():
    _, ev = make_ev()
    ev.begin_tick(60)
    assert ev.state == EVState.MISSED


def test_unfinished_charge_is_missed_after_deadline():
    _, ev = make_ev()
    ev.begin_tick(5)
    ev.begin_tick(45)
    assert ev.state == EVState.REQUESTED
    ev.begin_tick(46)
    assert ev.state == EVState.MISSED
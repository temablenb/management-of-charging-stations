import math

import pytest

from mas.charging_plan import (
    TICK_HOURS,
    build_schedule,
    energy_per_tick,
    expected_finish_tick,
    max_useful_power,
    meets_deadline,
    required_power_kw,
    slack_ticks,
    split_power,
    ticks_to_finish,
)
from mas.charging_queue import Order


def make_order(ev_id="ev-1", remaining=20.0, max_power=50.0, deadline=40):
    return Order(
        ev_id=ev_id, arrival_tick=0, energy_kwh=remaining,
        deadline_tick=deadline, max_power_kw=max_power,
        prepaid=False, remaining_kwh=remaining,
    )


def test_energy_per_tick():
    assert energy_per_tick(40.0) == 10.0
    assert energy_per_tick(0.0) == 0.0


def test_max_useful_power_limited_by_vehicle():
    assert max_useful_power(make_order(remaining=20.0, max_power=50.0)) == 50.0


def test_max_useful_power_limited_by_remaining_energy():
    assert max_useful_power(make_order(remaining=5.0, max_power=50.0)) == 20.0


def test_split_gives_equal_shares():
    orders = [make_order("a", max_power=50.0), make_order("b", max_power=50.0)]
    assert split_power(orders, 60.0) == {"a": 30.0, "b": 30.0}


def test_split_caps_small_limit_and_redistributes_surplus():
    orders = [
        make_order("a", max_power=10.0),
        make_order("b", max_power=50.0),
        make_order("c", max_power=50.0),
    ]
    assert split_power(orders, 70.0) == {"a": 10.0, "b": 30.0, "c": 30.0}


def test_split_gives_limits_when_power_is_enough():
    orders = [make_order("a", max_power=10.0), make_order("b", max_power=50.0)]
    assert split_power(orders, 200.0) == {"a": 10.0, "b": 50.0}


def test_split_total_does_not_exceed_available():
    orders = [make_order(f"ev-{i}", max_power=100.0) for i in range(3)]
    result = split_power(orders, 100.0)
    assert sum(result.values()) <= 100.0
    assert sum(result.values()) == pytest.approx(100.0, abs=1e-5)


def test_split_with_zero_available_gives_zero():
    orders = [make_order("a"), make_order("b")]
    assert split_power(orders, 0.0) == {"a": 0.0, "b": 0.0}


def test_split_without_orders_is_empty():
    assert split_power([], 100.0) == {}


def test_split_rejects_negative_power():
    with pytest.raises(ValueError):
        split_power([make_order()], -1.0)


def test_split_does_not_depend_on_order_of_orders():
    orders = [
        make_order("a", max_power=10.0),
        make_order("b", max_power=40.0),
        make_order("c", max_power=80.0),
    ]
    assert split_power(orders, 90.0) == split_power(list(reversed(orders)), 90.0)


def test_split_order_without_remaining_energy_gets_nothing():
    orders = [make_order("a", remaining=0.0), make_order("b", max_power=50.0)]
    assert split_power(orders, 30.0) == {"a": 0.0, "b": 30.0}




def test_ticks_to_finish_exact_and_rounded_up():
    assert ticks_to_finish(20.0, 40.0) == 2
    assert ticks_to_finish(30.0, 40.0) == 3
    assert ticks_to_finish(20.0, 30.0) == 3


def test_ticks_to_finish_without_energy_or_power():
    assert ticks_to_finish(0.0, 10.0) == 0
    assert ticks_to_finish(0.0, 0.0) == 0
    assert ticks_to_finish(10.0, 0.0) is None


def test_expected_finish_tick_adds_current_tick():
    assert expected_finish_tick(20.0, 40.0, 10) == 12
    assert expected_finish_tick(10.0, 0.0, 10) is None


def test_build_schedule_constant_power():
    assert build_schedule(20.0, 40.0) == (40.0, 40.0)


def test_build_schedule_last_tick_gets_remainder():
    assert build_schedule(20.0, 30.0) == (30.0, 30.0, 20.0)


def test_build_schedule_empty_without_power_or_energy():
    assert build_schedule(20.0, 0.0) == ()
    assert build_schedule(0.0, 40.0) == ()


def test_build_schedule_respects_horizon():
    assert len(build_schedule(1000.0, 1.0, horizon=5)) == 5


@pytest.mark.parametrize("remaining,power", [(20.0, 30.0), (33.3, 17.0), (7.5, 60.0), (100.0, 22.0)])
def test_schedule_delivers_exactly_remaining_energy(remaining, power):
    schedule = build_schedule(remaining, power)
    assert sum(schedule) * TICK_HOURS == pytest.approx(remaining, abs=1e-4)
    assert len(schedule) == ticks_to_finish(remaining, power)
    assert max(schedule) <= power + 1e-9


def test_meets_deadline():
    assert meets_deadline(12, 12)
    assert meets_deadline(10, 12)
    assert not meets_deadline(13, 12)
    assert not meets_deadline(None, 12)


def test_slack_ticks():
    assert slack_ticks(10, 12) == 2
    assert slack_ticks(14, 12) == -2
    assert slack_ticks(None, 12) is None


def test_required_power_to_meet_deadline():
    assert required_power_kw(20.0, 10, 30) == pytest.approx(4.0)


def test_required_power_edge_cases():
    assert required_power_kw(0.0, 10, 30) == 0.0
    assert required_power_kw(5.0, 30, 30) == math.inf
    assert required_power_kw(5.0, 31, 30) == math.inf
import pytest

from mas.charging_plan import energy_per_tick, max_useful_power, split_power
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
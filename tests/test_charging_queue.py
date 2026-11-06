import pytest

from mas.charging_queue import (
    PREPAID_BONUS_TICKS,
    ChargingQueue,
    Order,
    priority_score,
    waiting_ticks,
)
from mas.messages import ChargeRequest


def make_order(ev_id="ev-1", arrival=0, prepaid=False, energy=20.0):
    return Order(
        ev_id=ev_id, arrival_tick=arrival, energy_kwh=energy,
        deadline_tick=arrival + 40, max_power_kw=50.0,
        prepaid=prepaid, remaining_kwh=energy,
    )


def ids(orders):
    return [order.ev_id for order in orders]


def test_order_from_request():
    request = ChargeRequest(
        sender="ev-7", receiver="st-1", tick=5, energy_kwh=30.0,
        deadline_tick=25, max_power_kw=60.0, connector="CCS", prepaid=True,
    )
    order = Order.from_request(request)
    assert order.ev_id == "ev-7"
    assert order.arrival_tick == 5
    assert order.energy_kwh == 30.0
    assert order.remaining_kwh == 30.0
    assert order.deadline_tick == 25
    assert order.max_power_kw == 60.0
    assert order.prepaid
    assert order.start_tick is None


def test_waiting_ticks_never_negative():
    order = make_order(arrival=10)
    assert waiting_ticks(order, 14) == 4
    assert waiting_ticks(order, 3) == 0


def test_priority_grows_with_waiting():
    order = make_order(arrival=0)
    assert priority_score(order, 10) == 10
    assert priority_score(order, 14) == 14


def test_prepaid_adds_bonus():
    unpaid = make_order(arrival=0)
    paid = make_order(arrival=0, prepaid=True)
    assert priority_score(paid, 5) == priority_score(unpaid, 5) + PREPAID_BONUS_TICKS


def test_queue_requires_at_least_one_slot():
    with pytest.raises(ValueError):
        ChargingQueue(0)


def test_add_puts_order_in_waiting():
    queue = ChargingQueue(2)
    queue.add(make_order("ev-1"))
    assert "ev-1" in queue
    assert queue.waiting_count == 1
    assert queue.free_slots == 2


def test_duplicate_order_rejected():
    queue = ChargingQueue(2)
    queue.add(make_order("ev-1"))
    with pytest.raises(ValueError):
        queue.add(make_order("ev-1"))


def test_waiting_is_ordered_by_arrival():
    queue = ChargingQueue(2)
    queue.add(make_order("a", arrival=3))
    queue.add(make_order("b", arrival=1))
    queue.add(make_order("c", arrival=2))
    assert ids(queue.waiting(10)) == ["b", "c", "a"]


def test_prepaid_goes_ahead_of_slightly_earlier_unpaid():
    queue = ChargingQueue(2)
    queue.add(make_order("unpaid", arrival=0))
    queue.add(make_order("paid", arrival=5, prepaid=True))
    assert ids(queue.waiting(6)) == ["paid", "unpaid"]


def test_prepaid_does_not_beat_much_earlier_unpaid():
    queue = ChargingQueue(2)
    queue.add(make_order("unpaid", arrival=0))
    queue.add(make_order("paid", arrival=10, prepaid=True))
    assert ids(queue.waiting(12)) == ["unpaid", "paid"]


def test_equal_priority_ordered_by_ev_id():
    queue = ChargingQueue(2)
    queue.add(make_order("ev-2", arrival=1))
    queue.add(make_order("ev-1", arrival=1))
    assert ids(queue.waiting(5)) == ["ev-1", "ev-2"]


def test_admit_fills_free_slots_by_priority():
    queue = ChargingQueue(2)
    queue.add(make_order("a", arrival=0))
    queue.add(make_order("b", arrival=1))
    queue.add(make_order("c", arrival=2, prepaid=True))
    admitted = queue.admit(3)
    assert ids(admitted) == ["c", "a"]
    assert queue.free_slots == 0
    assert ids(queue.waiting(3)) == ["b"]


def test_admit_sets_start_tick():
    queue = ChargingQueue(1)
    queue.add(make_order("a", arrival=0))
    (order,) = queue.admit(4)
    assert order.start_tick == 4


def test_admit_does_nothing_when_full():
    queue = ChargingQueue(1)
    queue.add(make_order("a", arrival=0))
    queue.admit(1)
    queue.add(make_order("b", arrival=1))
    assert queue.admit(2) == []
    assert queue.waiting_count == 1


def test_remove_active_frees_slot_for_next():
    queue = ChargingQueue(1)
    queue.add(make_order("a", arrival=0))
    queue.add(make_order("b", arrival=1))
    queue.admit(2)
    queue.remove("a")
    assert ids(queue.admit(3)) == ["b"]


def test_remove_waiting_order():
    queue = ChargingQueue(2)
    order = make_order("a")
    queue.add(order)
    assert queue.remove("a") is order
    assert "a" not in queue


def test_remove_unknown_raises():
    with pytest.raises(KeyError):
        ChargingQueue(1).remove("ev-99")


def test_position_numbers_active_and_waiting():
    queue = ChargingQueue(1)
    queue.add(make_order("a", arrival=0))
    queue.add(make_order("b", arrival=1))
    queue.add(make_order("c", arrival=2))
    queue.admit(3)
    assert queue.position("a", 3) == 0
    assert queue.position("b", 3) == 1
    assert queue.position("c", 3) == 2


def test_position_unknown_raises():
    with pytest.raises(KeyError):
        ChargingQueue(1).position("ev-99", 0)


def test_active_lists_charging_orders():
    queue = ChargingQueue(2)
    order = make_order("a")
    queue.add(order)
    assert queue.active == ()
    queue.admit(1)
    assert queue.active == (order,)
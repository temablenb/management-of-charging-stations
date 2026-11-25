import pytest

from mas.bus import MessageBus
from mas.charging_queue import PREPAID_BONUS_TICKS, ChargingQueue, Order, priority_score
from mas.scenario import StationConfig
from mas.station_agent import StationAgent


def make_order(ev_id, arrival=0, prepaid=False):
    return Order(
        ev_id=ev_id, arrival_tick=arrival, energy_kwh=20.0, deadline_tick=arrival + 40,
        max_power_kw=50.0, prepaid=prepaid, remaining_kwh=20.0,
    )


def test_priority_score_uses_given_bonus():
    order = make_order("a", prepaid=True)
    assert priority_score(order, 5) == 5 + PREPAID_BONUS_TICKS
    assert priority_score(order, 5, prepaid_bonus=0) == 5
    assert priority_score(order, 5, prepaid_bonus=20) == 25


def test_queue_rejects_negative_bonus():
    with pytest.raises(ValueError):
        ChargingQueue(2, prepaid_bonus=-1)


def test_default_queue_keeps_prepaid_bonus():
    queue = ChargingQueue(1)
    queue.add(make_order("unpaid", arrival=0))
    queue.add(make_order("paid", arrival=5, prepaid=True))
    assert [order.ev_id for order in queue.waiting(6)] == ["paid", "unpaid"]


def test_fifo_queue_ignores_prepayment():
    queue = ChargingQueue(1, prepaid_bonus=0)
    queue.add(make_order("unpaid", arrival=0))
    queue.add(make_order("paid", arrival=5, prepaid=True))
    assert [order.ev_id for order in queue.waiting(6)] == ["unpaid", "paid"]


def test_fifo_queue_orders_strictly_by_arrival():
    queue = ChargingQueue(1, prepaid_bonus=0)
    for ev_id, arrival in (("c", 3), ("a", 1), ("b", 2)):
        queue.add(make_order(ev_id, arrival=arrival, prepaid=ev_id == "c"))
    assert [order.ev_id for order in queue.waiting(10)] == ["a", "b", "c"]


def test_station_fifo_flag_sets_queue_policy():
    config = StationConfig("st-1", 100.0, "CCS")
    assert StationAgent(MessageBus(), config).queue.prepaid_bonus == PREPAID_BONUS_TICKS
    assert StationAgent(MessageBus(), config, fifo=True).queue.prepaid_bonus == 0
    assert StationAgent(MessageBus(), config, fifo=True).fifo
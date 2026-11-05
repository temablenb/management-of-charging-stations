import pytest

from mas.bus import MessageBus, UnknownAgentError
from mas.messages import ChargeRequest


def make_request(sender="ev-1", receiver="st-1", tick=1):
    return ChargeRequest(
        sender=sender, receiver=receiver, tick=tick,
        energy_kwh=20.0, deadline_tick=tick + 10,
        max_power_kw=50.0, connector="CCS", prepaid=False,
    )


@pytest.fixture
def bus():
    bus = MessageBus()
    for agent_id in ("ev-1", "ev-2", "st-1", "grid"):
        bus.register(agent_id)
    return bus


def test_register_and_list_agents():
    bus = MessageBus()
    bus.register("grid")
    bus.register("st-1")
    assert bus.is_registered("grid")
    assert not bus.is_registered("st-2")
    assert bus.agents == ("grid", "st-1")


def test_register_duplicate_raises():
    bus = MessageBus()
    bus.register("grid")
    with pytest.raises(ValueError):
        bus.register("grid")


def test_send_to_unknown_receiver_raises(bus):
    with pytest.raises(UnknownAgentError):
        bus.send(make_request(receiver="st-99"))


def test_send_from_unknown_sender_raises(bus):
    with pytest.raises(UnknownAgentError):
        bus.send(make_request(sender="ev-99"))


def test_message_not_visible_before_deliver(bus):
    bus.send(make_request())
    assert bus.pending_count == 1
    assert bus.receive("st-1") == []


def test_deliver_moves_messages_to_receiver(bus):
    message = make_request()
    bus.send(message)
    assert bus.deliver() == 1
    assert bus.pending_count == 0
    assert bus.receive("st-1") == [message]


def test_receive_clears_inbox(bus):
    bus.send(make_request())
    bus.deliver()
    bus.receive("st-1")
    assert bus.receive("st-1") == []


def test_delivery_keeps_send_order(bus):
    first = make_request(sender="ev-1")
    second = make_request(sender="ev-2")
    bus.send(first)
    bus.send(second)
    bus.deliver()
    assert bus.receive("st-1") == [first, second]


def test_receive_unknown_agent_raises(bus):
    with pytest.raises(UnknownAgentError):
        bus.receive("st-99")


def test_deliver_without_messages_returns_zero(bus):
    assert bus.deliver() == 0
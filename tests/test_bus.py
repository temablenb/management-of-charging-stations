import pytest

from mas.bus import MessageBus, UnknownAgentError
from mas.messages import ChargeRequest, MessageType, PowerAllocation


def make_request(sender="ev-1", receiver="st-1", tick=1):
    return ChargeRequest(
        sender=sender, receiver=receiver, tick=tick,
        energy_kwh=20.0, deadline_tick=tick + 10,
        max_power_kw=50.0, connector="CCS", prepaid=False,
    )


def make_allocation(sender="grid", receiver="st-1", tick=1):
    return PowerAllocation(
        sender=sender, receiver=receiver, tick=tick,
        allocated_kw=40.0, tariff_multiplier=1.0,
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


def fill_bus(bus):
    bus.send(make_request(sender="ev-1", receiver="st-1", tick=1))
    bus.send(make_request(sender="ev-2", receiver="st-1", tick=2))
    bus.send(make_allocation(sender="grid", receiver="st-1", tick=3))
    bus.send(make_request(sender="st-1", receiver="grid", tick=4))
    bus.deliver()


def test_journal_records_only_delivered_messages(bus):
    bus.send(make_request())
    assert bus.journal == ()
    bus.deliver()
    assert len(bus.journal) == 1


def test_journal_entries_are_numbered_in_delivery_order(bus):
    bus.send(make_request(sender="ev-1"))
    bus.send(make_request(sender="ev-2"))
    bus.deliver()
    assert [entry.seq for entry in bus.journal] == [1, 2]
    assert bus.journal[1].message.sender == "ev-2"


def test_journal_is_kept_after_receive(bus):
    bus.send(make_request())
    bus.deliver()
    bus.receive("st-1")
    assert len(bus.journal) == 1


def test_filter_by_sender(bus):
    fill_bus(bus)
    result = bus.filter_journal(sender="ev-1")
    assert [e.message.sender for e in result] == ["ev-1"]


def test_filter_by_receiver(bus):
    fill_bus(bus)
    result = bus.filter_journal(receiver="grid")
    assert len(result) == 1
    assert result[0].message.sender == "st-1"


def test_filter_by_message_type(bus):
    fill_bus(bus)
    assert len(bus.filter_journal(message_type=MessageType.POWER_ALLOCATION)) == 1
    assert len(bus.filter_journal(message_type=MessageType.CHARGE_REQUEST)) == 3


def test_filter_by_tick_range_is_inclusive(bus):
    fill_bus(bus)
    result = bus.filter_journal(from_tick=2, to_tick=3)
    assert [e.message.tick for e in result] == [2, 3]


def test_filter_combines_conditions(bus):
    fill_bus(bus)
    result = bus.filter_journal(sender="grid", message_type=MessageType.CHARGE_REQUEST)
    assert result == []


def test_filter_without_conditions_returns_all(bus):
    fill_bus(bus)
    assert len(bus.filter_journal()) == 4


def test_count_by_type(bus):
    fill_bus(bus)
    assert bus.count_by_type() == {
        MessageType.CHARGE_REQUEST: 3,
        MessageType.POWER_ALLOCATION: 1,
    }


def test_reset_clears_state_but_keeps_agents(bus):
    fill_bus(bus)
    bus.send(make_request())
    bus.reset()
    assert bus.journal == ()
    assert bus.pending_count == 0
    assert bus.receive("st-1") == []
    assert bus.is_registered("st-1")
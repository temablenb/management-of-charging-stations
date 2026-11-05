import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.messages import ChargePlan, ChargeRequest, MessageType


def make_request(sender="ev-1", receiver="st-1", tick=1):
    return ChargeRequest(
        sender=sender, receiver=receiver, tick=tick,
        energy_kwh=20.0, deadline_tick=tick + 10,
        max_power_kw=50.0, connector="CCS", prepaid=False,
    )


class Recorder(BaseAgent):
    def __init__(self, agent_id, bus):
        super().__init__(agent_id, bus)
        self.received = []

    def handle(self, message):
        self.received.append(message)


class Echo(BaseAgent):
    def handle(self, message):
        self.send(ChargePlan(
            sender=self.agent_id, receiver=message.sender, tick=message.tick,
            schedule_kw=(10.0,), expected_finish_tick=message.tick + 1,
            queue_position=0,
        ))


def test_agent_registers_on_bus():
    bus = MessageBus()
    Recorder("ev-1", bus)
    assert bus.is_registered("ev-1")


def test_duplicate_agent_id_rejected():
    bus = MessageBus()
    Recorder("ev-1", bus)
    with pytest.raises(ValueError):
        Recorder("ev-1", bus)


def test_send_goes_through_bus():
    bus = MessageBus()
    ev = Recorder("ev-1", bus)
    Recorder("st-1", bus)
    ev.send(make_request())
    assert bus.pending_count == 1


def test_send_rejects_foreign_sender():
    bus = MessageBus()
    ev = Recorder("ev-1", bus)
    Recorder("ev-2", bus)
    Recorder("st-1", bus)
    with pytest.raises(ValueError):
        ev.send(make_request(sender="ev-2"))


def test_process_inbox_handles_messages_in_order():
    bus = MessageBus()
    st = Recorder("st-1", bus)
    ev1 = Recorder("ev-1", bus)
    ev2 = Recorder("ev-2", bus)
    first, second = make_request(sender="ev-1"), make_request(sender="ev-2")
    ev1.send(first)
    ev2.send(second)
    bus.deliver()
    assert st.process_inbox() == 2
    assert st.received == [first, second]


def test_process_inbox_empty_returns_zero():
    bus = MessageBus()
    st = Recorder("st-1", bus)
    assert st.process_inbox() == 0


def test_base_handle_is_not_implemented():
    bus = MessageBus()
    ev = Recorder("ev-1", bus)
    plain = BaseAgent("st-1", bus)
    ev.send(make_request())
    bus.deliver()
    with pytest.raises(NotImplementedError):
        plain.process_inbox()


def test_tick_hooks_do_nothing_by_default():
    agent = BaseAgent("a-1", MessageBus())
    assert agent.begin_tick(0) is None
    assert agent.end_tick(0) is None


def test_reply_chain_between_agents():
    bus = MessageBus()
    ev = Recorder("ev-1", bus)
    st = Echo("st-1", bus)
    ev.send(make_request())
    bus.deliver()
    st.process_inbox()
    bus.deliver()
    ev.process_inbox()
    assert ev.received[0].type == MessageType.CHARGE_PLAN
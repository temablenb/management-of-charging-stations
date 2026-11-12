import pytest

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.messages import MessageType, PowerAllocation, StorageDispatch, StorageOffer
from mas.scenario import StorageConfig
from mas.storage_agent import (
    CHARGE,
    DISCHARGE,
    IDLE,
    MAX_SOC,
    MIN_SOC,
    StorageAgent,
    mode_for_tick,
)


def make_storage(**overrides):
    params = dict(capacity_kwh=200.0, max_power_kw=60.0, efficiency=0.9, initial_soc=0.5)
    params.update(overrides)
    return StorageAgent(MessageBus(), StorageConfig(**params))


def test_storage_registers_on_bus():
    bus = MessageBus()
    StorageAgent(bus, StorageConfig(200.0, 60.0))
    assert bus.is_registered("storage")


def test_initial_state_from_config():
    storage = make_storage()
    assert storage.soc == pytest.approx(0.5)
    assert storage.energy_kwh == pytest.approx(100.0)
    assert storage.min_energy_kwh == pytest.approx(20.0)
    assert storage.max_energy_kwh == pytest.approx(190.0)


def test_initial_soc_is_clamped_to_limits():
    assert make_storage(initial_soc=0.0).soc == MIN_SOC
    assert make_storage(initial_soc=1.0).soc == MAX_SOC


def test_invalid_soc_limits_rejected():
    with pytest.raises(ValueError):
        StorageAgent(MessageBus(), StorageConfig(200.0, 60.0), min_soc=0.9, max_soc=0.5)


def test_charge_stores_energy_with_losses():
    storage = make_storage()
    accepted = storage.charge(40.0)
    assert accepted == 40.0
    assert storage.energy_kwh == pytest.approx(100.0 + 40.0 * 0.25 * 0.9)
    assert storage.charged_kwh == pytest.approx(10.0)


def test_charge_is_limited_by_max_power():
    storage = make_storage()
    assert storage.charge(500.0) == 60.0


def test_charge_is_limited_by_free_capacity():
    storage = make_storage(initial_soc=0.94)
    accepted = storage.charge(60.0)
    assert accepted == pytest.approx(2.0 / (0.25 * 0.9))
    assert storage.soc == pytest.approx(0.95)
    assert storage.max_charge_kw() == pytest.approx(0.0, abs=1e-9)


def test_discharge_spends_energy_with_losses():
    storage = make_storage()
    delivered = storage.discharge(40.0)
    assert delivered == 40.0
    assert storage.energy_kwh == pytest.approx(100.0 - 40.0 * 0.25 / 0.9)
    assert storage.discharged_kwh == pytest.approx(10.0)


def test_discharge_is_limited_by_max_power():
    assert make_storage().discharge(500.0) == 60.0


def test_discharge_is_limited_by_reserve_above_minimum():
    storage = make_storage(initial_soc=0.11)
    delivered = storage.discharge(60.0)
    assert delivered == pytest.approx(2.0 * 0.9 / 0.25)
    assert storage.soc == pytest.approx(0.10)
    assert storage.max_discharge_kw() == pytest.approx(0.0, abs=1e-9)


def test_soc_never_leaves_limits_over_many_cycles():
    storage = make_storage()
    for step in range(400):
        if step % 7 < 3:
            storage.charge(60.0)
        else:
            storage.discharge(60.0)
        assert MIN_SOC - 1e-9 <= storage.soc <= MAX_SOC + 1e-9


def test_round_trip_loses_energy():
    storage = make_storage()
    before = storage.energy_kwh
    storage.charge(40.0)
    storage.discharge(40.0)
    assert storage.energy_kwh < before + 1e-9
    assert storage.energy_kwh == pytest.approx(before + 40 * 0.25 * 0.9 - 40 * 0.25 / 0.9)


def test_negative_power_rejected():
    storage = make_storage()
    with pytest.raises(ValueError):
        storage.charge(-1.0)
    with pytest.raises(ValueError):
        storage.discharge(-1.0)


def test_empty_request_changes_nothing():
    storage = make_storage()
    assert storage.charge(0.0) == 0.0
    assert storage.discharge(0.0) == 0.0
    assert storage.soc == pytest.approx(0.5)


def make_network(**overrides):
    bus = MessageBus()
    grid = BaseAgent("grid", bus)
    params = dict(capacity_kwh=200.0, max_power_kw=60.0, efficiency=0.9, initial_soc=0.5)
    params.update(overrides)
    storage = StorageAgent(bus, StorageConfig(**params))
    return bus, grid, storage


def test_mode_by_tariff_zone():
    assert mode_for_tick(2) == CHARGE        # 00:30, ночь
    assert mode_for_tick(30) == DISCHARGE    # 07:30, утренний пик
    assert mode_for_tick(48) == IDLE         # 12:00, день
    assert mode_for_tick(72) == DISCHARGE    # 18:00, вечерний пик
    assert mode_for_tick(92) == CHARGE       # 23:00, ночь


def test_night_tick_sends_charge_request():
    bus, _, storage = make_network()
    storage.begin_tick(2)
    bus.deliver()
    (request,) = bus.receive("grid")
    assert request.type == MessageType.POWER_REQUEST
    assert request.sender == "storage"
    assert request.demand_kw == 60.0
    assert request.max_power_kw == 60.0
    assert request.priority == 0.5
    assert storage.mode == CHARGE


def test_night_tick_without_room_sends_nothing():
    bus, _, storage = make_network(initial_soc=0.95)
    storage.begin_tick(2)
    assert bus.pending_count == 0


def test_peak_tick_sends_storage_offer():
    bus, _, storage = make_network()
    storage.begin_tick(72)
    bus.deliver()
    (offer,) = bus.receive("grid")
    assert offer.type == MessageType.STORAGE_OFFER
    assert offer.available_kw == 60.0
    assert offer.soc == pytest.approx(0.5)
    assert storage.mode == DISCHARGE


def test_peak_offer_is_limited_by_reserve():
    bus, _, storage = make_network(initial_soc=0.11)
    storage.begin_tick(72)
    bus.deliver()
    (offer,) = bus.receive("grid")
    assert offer.available_kw == pytest.approx(7.2)


def test_day_tick_is_idle():
    bus, _, storage = make_network()
    storage.begin_tick(48)
    assert bus.pending_count == 0
    assert storage.mode == IDLE


def test_allocation_charges_storage():
    bus, grid, storage = make_network()
    storage.begin_tick(2)
    grid.send(PowerAllocation(sender="grid", receiver="storage", tick=2,
                              allocated_kw=40.0, tariff_multiplier=1.0))
    bus.deliver()
    storage.process_inbox()
    assert storage.charge_kw == 40.0
    assert storage.soc == pytest.approx(0.5 + 40 * 0.25 * 0.9 / 200)


def test_dispatch_discharges_storage():
    bus, grid, storage = make_network()
    storage.begin_tick(72)
    grid.send(StorageDispatch(sender="grid", receiver="storage", tick=72, discharge_kw=30.0))
    bus.deliver()
    storage.process_inbox()
    assert storage.discharge_kw == 30.0
    assert storage.soc < 0.5


def test_message_from_other_tick_is_rejected():
    bus, grid, storage = make_network()
    storage.begin_tick(72)
    grid.send(StorageDispatch(sender="grid", receiver="storage", tick=71, discharge_kw=30.0))
    bus.deliver()
    with pytest.raises(ValueError):
        storage.process_inbox()


def test_unexpected_message_type_is_rejected():
    bus, grid, storage = make_network()
    grid.send(StorageOffer(sender="grid", receiver="storage", tick=1, available_kw=1.0, soc=0.5))
    bus.deliver()
    with pytest.raises(NotImplementedError):
        storage.process_inbox()


def test_begin_tick_resets_tick_values():
    bus, grid, storage = make_network()
    storage.begin_tick(72)
    grid.send(StorageDispatch(sender="grid", receiver="storage", tick=72, discharge_kw=30.0))
    bus.deliver()
    storage.process_inbox()
    storage.begin_tick(73)
    assert storage.discharge_kw == 0.0
    assert storage.charge_kw == 0.0


def test_end_tick_records_soc_history():
    _, _, storage = make_network()
    storage.end_tick(0)
    storage.charge(60.0)
    storage.end_tick(1)
    assert len(storage.soc_history) == 2
    assert storage.soc_history[1] > storage.soc_history[0]
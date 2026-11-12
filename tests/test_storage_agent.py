import pytest

from mas.bus import MessageBus
from mas.scenario import StorageConfig
from mas.storage_agent import MAX_SOC, MIN_SOC, StorageAgent


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
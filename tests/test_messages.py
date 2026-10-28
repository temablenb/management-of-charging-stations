import dataclasses

import pytest

from mas.messages import (
    ChargePlan,
    ChargeRequest,
    Message,
    MessageType,
    PowerAllocation,
    PowerRequest,
    StorageOffer,
)


def make_request(**overrides):
    params = dict(
        sender="ev-1", receiver="st-1", tick=10,
        energy_kwh=30.0, deadline_tick=30,
        max_power_kw=50.0, connector="CCS", prepaid=False,
    )
    params.update(overrides)
    return ChargeRequest(**params)


def test_base_message_has_no_type():
    with pytest.raises(NotImplementedError):
        Message(sender="a", receiver="b", tick=0).type


def test_charge_request_type():
    assert make_request().type == MessageType.CHARGE_REQUEST


def test_charge_request_rejects_non_positive_energy():
    with pytest.raises(ValueError):
        make_request(energy_kwh=0)


def test_charge_request_rejects_deadline_not_after_current_tick():
    with pytest.raises(ValueError):
        make_request(deadline_tick=10)


def test_messages_are_immutable():
    request = make_request()
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.energy_kwh = 99.0


def test_charge_plan_keeps_schedule():
    plan = ChargePlan(
        sender="st-1", receiver="ev-1", tick=11,
        schedule_kw=(10.0, 10.0, 5.0),
        expected_finish_tick=14, queue_position=0,
    )
    assert plan.type == MessageType.CHARGE_PLAN
    assert sum(plan.schedule_kw) == 25.0


def test_power_request_type_and_forecast():
    request = PowerRequest(
        sender="st-1", receiver="grid", tick=5,
        demand_kw=60.0, max_power_kw=100.0, forecast_kw=(55.0, 70.0),
    )
    assert request.type == MessageType.POWER_REQUEST
    assert request.forecast_kw[1] == 70.0


def test_power_request_rejects_negative_demand():
    with pytest.raises(ValueError):
        PowerRequest(
            sender="st-1", receiver="grid", tick=5,
            demand_kw=-1.0, max_power_kw=100.0, forecast_kw=(),
        )


def test_power_allocation_type():
    allocation = PowerAllocation(
        sender="grid", receiver="st-1", tick=5,
        allocated_kw=40.0, tariff_multiplier=1.2,
    )
    assert allocation.type == MessageType.POWER_ALLOCATION


def test_power_allocation_rejects_non_positive_multiplier():
    with pytest.raises(ValueError):
        PowerAllocation(
            sender="grid", receiver="st-1", tick=5,
            allocated_kw=40.0, tariff_multiplier=0.0,
        )


def test_storage_offer_rejects_soc_out_of_range():
    with pytest.raises(ValueError):
        StorageOffer(
            sender="storage", receiver="grid", tick=5,
            available_kw=20.0, soc=1.5,
        )
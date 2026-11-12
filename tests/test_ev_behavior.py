import pytest

from mas.ev_behavior import (
    MAX_SAVING,
    SAFETY_FACTOR,
    choose_start_tick,
    latest_start_tick,
    min_charge_ticks,
)

# 36 кВт·ч на 50 кВт: 3 такта на полной мощности, с запасом 1,5 это 5 тактов
ENERGY, POWER = 36.0, 50.0
PEAK_18_00, DAY_12_00, NIGHT_23_00 = 72, 48, 92


def start(arrival, deadline, sensitivity):
    return choose_start_tick(arrival, deadline, ENERGY, POWER, sensitivity)


def test_min_charge_ticks():
    assert min_charge_ticks(36.0, 50.0) == 3
    assert min_charge_ticks(25.0, 100.0) == 1
    assert min_charge_ticks(25.0, 50.0) == 2


def test_latest_start_tick_keeps_safety_margin():
    assert SAFETY_FACTOR == 1.5
    assert latest_start_tick(ENERGY, POWER, 150) == 145


def test_zero_sensitivity_never_shifts():
    assert start(PEAK_18_00, 112, 0.0) == PEAK_18_00


def test_shifts_from_peak_to_cheaper_zone():
    assert start(PEAK_18_00, 112, 1.0) == NIGHT_23_00


def test_moderate_sensitivity_still_shifts_for_big_saving():
    assert start(PEAK_18_00, 112, 0.5) == NIGHT_23_00


def test_low_sensitivity_requires_bigger_saving():
    assert start(DAY_12_00, 108, 0.4) == DAY_12_00
    assert start(DAY_12_00, 108, 0.6) == NIGHT_23_00


def test_no_cheaper_tick_inside_available_window():
    assert start(PEAK_18_00, 78, 1.0) == PEAK_18_00


def test_shift_is_limited_by_latest_start():
    assert start(PEAK_18_00, 90, 1.0) == 84


def test_small_saving_is_not_enough_for_medium_sensitivity():
    assert start(PEAK_18_00, 90, 0.5) == PEAK_18_00


def test_no_shift_when_arrival_is_already_cheapest():
    assert start(NIGHT_23_00, 130, 1.0) == NIGHT_23_00


def test_shift_never_exceeds_latest_start():
    for arrival in range(0, 96, 7):
        deadline = arrival + 50
        chosen = start(arrival, deadline, 1.0)
        assert arrival <= chosen <= max(arrival, latest_start_tick(ENERGY, POWER, deadline))


def test_max_saving_constant():
    assert MAX_SAVING == pytest.approx(0.3)
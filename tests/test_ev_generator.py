import numpy as np
import pytest

from mas.clock import TICKS_PER_DAY, hour_of_tick
from mas.ev_generator import HOUR_WEIGHTS, arrival_probabilities, generate_arrival_ticks


def test_probabilities_sum_to_one():
    probabilities = arrival_probabilities()
    assert len(probabilities) == 24
    assert probabilities.sum() == pytest.approx(1.0)


def test_probabilities_have_morning_and_evening_peaks():
    probabilities = arrival_probabilities()
    night = probabilities[0:7].mean()
    midday = probabilities[10:17].mean()
    morning = probabilities[7:10].mean()
    evening = probabilities[17:21].mean()
    assert night < midday < morning < evening


def test_probabilities_reject_wrong_length():
    with pytest.raises(ValueError):
        arrival_probabilities([1.0] * 23)


def test_probabilities_reject_negative_or_zero_weights():
    with pytest.raises(ValueError):
        arrival_probabilities([-1.0] + [1.0] * 23)
    with pytest.raises(ValueError):
        arrival_probabilities([0.0] * 24)


def test_default_weights_cover_24_hours():
    assert len(HOUR_WEIGHTS) == 24


def test_arrival_count_is_exact():
    ticks = generate_arrival_ticks(50, 3, np.random.default_rng(1))
    assert len(ticks) == 150


def test_arrivals_are_sorted_and_inside_horizon():
    ticks = generate_arrival_ticks(40, 2, np.random.default_rng(2))
    assert ticks == sorted(ticks)
    assert 0 <= ticks[0] and ticks[-1] < 2 * TICKS_PER_DAY


def test_each_day_gets_its_own_arrivals():
    ticks = generate_arrival_ticks(30, 3, np.random.default_rng(3))
    for day in range(3):
        count = sum(1 for tick in ticks if tick // TICKS_PER_DAY == day)
        assert count == 30


def test_arrivals_follow_daily_profile():
    ticks = generate_arrival_ticks(2000, 1, np.random.default_rng(4))
    hours = [hour_of_tick(tick) for tick in ticks]
    evening = sum(1 for hour in hours if 17 <= hour < 21)
    night = sum(1 for hour in hours if hour < 7)
    assert evening > 4 * night
    assert evening / len(ticks) == pytest.approx(10 / 27, abs=0.04)


def test_arrivals_are_reproducible_by_seed():
    first = generate_arrival_ticks(40, 2, np.random.default_rng(5))
    second = generate_arrival_ticks(40, 2, np.random.default_rng(5))
    assert first == second


def test_arrivals_depend_on_seed():
    first = generate_arrival_ticks(40, 2, np.random.default_rng(5))
    second = generate_arrival_ticks(40, 2, np.random.default_rng(6))
    assert first != second


def test_zero_arrivals_per_day_gives_empty_list():
    assert generate_arrival_ticks(0, 2, np.random.default_rng(1)) == []


def test_arrival_inputs_are_validated():
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError):
        generate_arrival_ticks(-1, 1, rng)
    with pytest.raises(ValueError):
        generate_arrival_ticks(10, 0, rng)
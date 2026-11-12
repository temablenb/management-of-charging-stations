from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from mas.clock import TICKS_PER_DAY, hour_of_tick
from mas.ev_generator import (
    HOUR_WEIGHTS,
    arrival_probabilities,
    generate_arrival_ticks,
    generate_profiles,
    vehicle_rng,
)
from mas.ev_models import EVModel, load_ev_models
from mas.scenario import load_scenario

ROOT = Path(__file__).resolve().parent.parent
CONFIG = load_scenario(ROOT / "scenarios" / "default.json")
MODELS = load_ev_models(ROOT / "scenarios" / "ev_models.json")


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


def test_profiles_count_and_order():
    profiles = generate_profiles(CONFIG, MODELS)
    assert len(profiles) == CONFIG.ev_per_day * CONFIG.days
    arrivals = [profile.arrival_tick for profile in profiles]
    assert arrivals == sorted(arrivals)


def test_profile_ids_are_unique_and_numbered():
    profiles = generate_profiles(CONFIG, MODELS)
    ids = [profile.ev_id for profile in profiles]
    assert len(set(ids)) == len(ids)
    assert ids[0] == "ev-0001"
    assert ids[-1] == f"ev-{len(ids):04d}"


def test_profiles_use_only_connectors_present_on_stations():
    profiles = generate_profiles(CONFIG, MODELS)
    assert {profile.connector for profile in profiles} <= {"CCS", "GB/T"}


def test_profiles_are_reproducible_by_seed():
    assert generate_profiles(CONFIG, MODELS) == generate_profiles(CONFIG, MODELS)


def test_profiles_depend_on_seed():
    other = replace(CONFIG, seed=CONFIG.seed + 1)
    assert generate_profiles(CONFIG, MODELS) != generate_profiles(other, MODELS)


def test_sensitive_and_prepaid_shares_are_respected():
    config = replace(CONFIG, ev_per_day=500, days=2, sensitive_share=0.5, prepaid_share=0.1)
    profiles = generate_profiles(config, MODELS)
    sensitive = sum(1 for profile in profiles if profile.price_sensitivity > 0) / len(profiles)
    prepaid = sum(1 for profile in profiles if profile.prepaid) / len(profiles)
    assert sensitive == pytest.approx(0.5, abs=0.05)
    assert prepaid == pytest.approx(0.1, abs=0.04)


def test_zero_shares_give_insensitive_vehicles_without_prepayment():
    config = replace(CONFIG, sensitive_share=0.0, prepaid_share=0.0)
    profiles = generate_profiles(config, MODELS)
    assert all(profile.price_sensitivity == 0.0 for profile in profiles)
    assert not any(profile.prepaid for profile in profiles)


def test_sensitivity_values_are_in_expected_range():
    config = replace(CONFIG, sensitive_share=1.0)
    profiles = generate_profiles(config, MODELS)
    assert all(0.4 <= profile.price_sensitivity <= 1.0 for profile in profiles)


def test_profiles_soc_and_deadlines_are_consistent():
    for profile in generate_profiles(CONFIG, MODELS):
        assert 0.1 <= profile.soc <= 0.5
        assert profile.target_soc == 0.8
        assert profile.deadline_tick > profile.arrival_tick


def test_no_vehicles_when_scenario_has_none():
    config = replace(CONFIG, ev_per_day=0)
    assert generate_profiles(config, MODELS) == []


def test_error_when_no_model_matches_station_connectors():
    only_chademo = (EVModel("Nissan", "Leaf", 40.0, 50.0, "CHAdeMO"),)
    with pytest.raises(ValueError):
        generate_profiles(CONFIG, only_chademo)


def test_vehicle_rng_is_reproducible_and_per_vehicle():
    assert vehicle_rng(42, "ev-0001").integers(1_000_000) == vehicle_rng(42, "ev-0001").integers(1_000_000)
    values = {int(vehicle_rng(42, f"ev-{i:04d}").integers(1_000_000)) for i in range(1, 20)}
    assert len(values) > 10


def test_vehicle_rng_depends_on_seed():
    assert vehicle_rng(1, "ev-0001").integers(1_000_000) != vehicle_rng(2, "ev-0001").integers(1_000_000)
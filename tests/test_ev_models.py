import json
from pathlib import Path

import numpy as np
import pytest

from mas.ev_behavior import SAFETY_FACTOR, min_charge_ticks
from mas.ev_models import EVModel, load_ev_models, make_profile

CATALOG = Path(__file__).resolve().parent.parent / "scenarios" / "ev_models.json"


def sample_model(**overrides):
    params = dict(brand="BYD", model="Dolphin", battery_kwh=45.0,
                  max_charge_kw=60.0, connector="CCS")
    params.update(overrides)
    return EVModel(**params)


def write_catalog(tmp_path, items):
    path = tmp_path / "models.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def test_catalog_loads_all_models():
    models = load_ev_models(CATALOG)
    assert len(models) == 30
    assert {model.connector for model in models} == {"CCS", "CHAdeMO", "Type2", "GB/T"}


def test_catalog_contains_known_model():
    models = {model.name: model for model in load_ev_models(CATALOG)}
    tesla = models["Tesla Model 3 Long Range"]
    assert tesla.battery_kwh == 82.0
    assert tesla.max_charge_kw == 250.0


def test_model_name():
    assert sample_model().name == "BYD Dolphin"


def test_model_validation():
    with pytest.raises(ValueError):
        sample_model(battery_kwh=0)
    with pytest.raises(ValueError):
        sample_model(max_charge_kw=-1)
    with pytest.raises(ValueError):
        sample_model(connector="Schuko")
    with pytest.raises(ValueError):
        sample_model(brand="")


def test_load_rejects_empty_catalog(tmp_path):
    with pytest.raises(ValueError):
        load_ev_models(write_catalog(tmp_path, []))


def test_load_rejects_missing_field(tmp_path):
    items = [{"brand": "BYD", "model": "Dolphin", "battery_kwh": 45, "connector": "CCS"}]
    with pytest.raises(ValueError, match="max_charge_kw"):
        load_ev_models(write_catalog(tmp_path, items))


def test_load_rejects_duplicates(tmp_path):
    item = {"brand": "BYD", "model": "Dolphin", "battery_kwh": 45,
            "max_charge_kw": 60, "connector": "CCS"}
    with pytest.raises(ValueError):
        load_ev_models(write_catalog(tmp_path, [item, item]))


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_ev_models(tmp_path / "no.json")


def test_profile_copies_model_parameters():
    profile = make_profile(sample_model(), "ev-1", 10, np.random.default_rng(1))
    assert profile.ev_id == "ev-1"
    assert profile.battery_kwh == 45.0
    assert profile.max_charge_kw == 60.0
    assert profile.connector == "CCS"
    assert profile.arrival_tick == 10


def test_profile_is_reproducible_by_seed():
    first = make_profile(sample_model(), "ev-1", 10, np.random.default_rng(5))
    second = make_profile(sample_model(), "ev-1", 10, np.random.default_rng(5))
    assert first == second


def test_profile_depends_on_seed():
    profiles = {make_profile(sample_model(), "ev-1", 10, np.random.default_rng(s)).soc
                for s in range(10)}
    assert len(profiles) > 1


def test_profile_soc_is_inside_range():
    for seed in range(30):
        profile = make_profile(sample_model(), "ev-1", 0, np.random.default_rng(seed),
                               soc_range=(0.2, 0.4))
        assert 0.2 <= profile.soc <= 0.4
        assert profile.target_soc == 0.8


def test_profile_deadline_allows_charging_with_margin():
    model = sample_model(battery_kwh=100.0, max_charge_kw=22.0)
    for seed in range(20):
        profile = make_profile(model, "ev-1", 0, np.random.default_rng(seed),
                               parking_hours=(0.5, 1.0))
        needed = min_charge_ticks(profile.needed_kwh, profile.max_charge_kw)
        assert profile.deadline_tick >= int(needed * SAFETY_FACTOR)


def test_profile_passes_flags():
    profile = make_profile(sample_model(), "ev-1", 0, np.random.default_rng(1),
                           prepaid=True, price_sensitivity=0.7)
    assert profile.prepaid
    assert profile.price_sensitivity == 0.7


def test_profile_rejects_bad_ranges():
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError):
        make_profile(sample_model(), "ev-1", 0, rng, soc_range=(0.5, 0.9))
    with pytest.raises(ValueError):
        make_profile(sample_model(), "ev-1", 0, rng, parking_hours=(3.0, 1.0))
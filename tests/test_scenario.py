from dataclasses import replace
from pathlib import Path

import pytest

from mas.scenario import ScenarioConfig, StationConfig, StorageConfig, load_scenario

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "default.json"


def make_data(**overrides):
    data = {
        "name": "test", "seed": 1, "days": 2,
        "substation_limit_kw": 200.0, "base_tariff_rub": 10.0,
        "tariff_min_mult": 0.7, "tariff_max_mult": 1.6, "ev_per_day": 10,
        "stations": [
            {"station_id": "st-1", "max_power_kw": 100.0, "connector": "CCS"},
            {"station_id": "st-2", "max_power_kw": 80.0, "connector": "GB/T"},
        ],
    }
    data.update(overrides)
    return data


def test_default_scenario_loads():
    config = load_scenario(DEFAULT_PATH)
    assert config.name == "default"
    assert len(config.stations) == 7
    assert config.substation_limit_kw == 420.0
    assert config.stations[0].slots == 5
    assert config.storage is not None


def test_scenario_without_storage_has_none():
    assert ScenarioConfig.from_dict(make_data()).storage is None


def test_rng_is_reproducible():
    config = ScenarioConfig.from_dict(make_data())
    assert (config.rng().random(5) == config.rng().random(5)).all()


def test_rng_depends_on_seed():
    config = ScenarioConfig.from_dict(make_data())
    other = replace(config, seed=2)
    assert (config.rng().random(5) != other.rng().random(5)).any()


def test_missing_fields_raise():
    data = make_data()
    del data["days"]
    with pytest.raises(ValueError, match="days"):
        ScenarioConfig.from_dict(data)


def test_non_positive_limit_rejected():
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(make_data(substation_limit_kw=0))


def test_tariff_range_must_be_ordered():
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(make_data(tariff_min_mult=1.6, tariff_max_mult=0.7))


def test_days_must_be_positive():
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(make_data(days=0))


def test_empty_stations_rejected():
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(make_data(stations=[]))


def test_duplicate_station_ids_rejected():
    stations = [
        {"station_id": "st-1", "max_power_kw": 100.0, "connector": "CCS"},
        {"station_id": "st-1", "max_power_kw": 80.0, "connector": "CCS"},
    ]
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(make_data(stations=stations))


def test_station_slots_must_be_positive():
    with pytest.raises(ValueError):
        StationConfig("st-1", 100.0, "CCS", slots=0)


def test_storage_efficiency_range():
    with pytest.raises(ValueError):
        StorageConfig(100.0, 50.0, efficiency=1.5)


def test_storage_initial_soc_range():
    with pytest.raises(ValueError):
        StorageConfig(100.0, 50.0, initial_soc=-0.1)


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_scenario(tmp_path / "no.json")


def test_shares_have_defaults():
    config = ScenarioConfig.from_dict(make_data())
    assert config.sensitive_share == 0.3
    assert config.prepaid_share == 0.2


def test_shares_are_read_from_data():
    config = ScenarioConfig.from_dict(make_data(sensitive_share=0.5, prepaid_share=0.1))
    assert config.sensitive_share == 0.5
    assert config.prepaid_share == 0.1


def test_sensitive_share_out_of_range_rejected():
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(make_data(sensitive_share=1.5))


def test_prepaid_share_out_of_range_rejected():
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(make_data(prepaid_share=-0.1))
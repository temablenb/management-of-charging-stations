from dataclasses import replace
from pathlib import Path

import pytest

from mas.engine import Simulation
from mas.ev_generator import generate_profiles
from mas.ev_models import load_ev_models
from mas.metrics import OVERLOAD_TOLERANCE_KW, TickRecord, collect_tick
from mas.scenario import ScenarioConfig

MODELS = load_ev_models(Path(__file__).resolve().parent.parent / "scenarios" / "ev_models.json")


def small_config(**overrides):
    data = {
        "name": "small", "seed": 3, "days": 1,
        "substation_limit_kw": 200.0, "base_tariff_rub": 10.0,
        "tariff_min_mult": 0.7, "tariff_max_mult": 1.6, "ev_per_day": 30,
        "stations": [
            {"station_id": "st-1", "max_power_kw": 100.0, "connector": "CCS"},
            {"station_id": "st-2", "max_power_kw": 100.0, "connector": "CCS"},
            {"station_id": "st-3", "max_power_kw": 80.0, "connector": "GB/T"},
        ],
        "storage": {"capacity_kwh": 200.0, "max_power_kw": 60.0},
    }
    data.update(overrides)
    return ScenarioConfig.from_dict(data)


def make_record(**overrides):
    params = dict(
        tick=0, station_kw={"st-1": 40.0, "st-2": 30.0}, charging={"st-1": 2, "st-2": 1},
        waiting={"st-1": 0, "st-2": 0}, price={"st-1": 10.0, "st-2": 12.0},
        storage_charge_kw=0.0, storage_discharge_kw=0.0, storage_soc=0.5, limit_kw=100.0,
    )
    params.update(overrides)
    return TickRecord(**params)


@pytest.fixture(scope="module")
def finished_sim():
    config = small_config()
    sim = Simulation(config, generate_profiles(config, MODELS), warmup_days=1)
    sim.run()
    return sim


def test_stations_kw_is_sum_over_stations():
    assert make_record().stations_kw == 70.0


def test_grid_kw_adds_storage_charge_and_subtracts_discharge():
    assert make_record(storage_charge_kw=20.0).grid_kw == 90.0
    assert make_record(storage_discharge_kw=15.0).grid_kw == 55.0


def test_overload_is_excess_over_limit():
    record = make_record(station_kw={"st-1": 90.0, "st-2": 30.0})
    assert record.overload_kw == 20.0
    assert record.is_overloaded


def test_no_overload_within_limit_or_with_tolerance():
    assert make_record().overload_kw == 0.0
    assert not make_record().is_overloaded
    edge = make_record(station_kw={"st-1": 100.0 + OVERLOAD_TOLERANCE_KW / 2})
    assert not edge.is_overloaded


def test_storage_discharge_removes_overload():
    record = make_record(station_kw={"st-1": 90.0, "st-2": 30.0}, storage_discharge_kw=20.0)
    assert record.overload_kw == 0.0


def test_one_record_per_tick(finished_sim):
    assert len(finished_sim.records) == finished_sim.total_ticks
    assert [record.tick for record in finished_sim.records] == list(range(finished_sim.total_ticks))


def test_record_covers_all_stations(finished_sim):
    record = finished_sim.records[40]
    assert set(record.station_kw) == {"st-1", "st-2", "st-3"}
    assert set(record.price) == set(record.charging) == set(record.waiting)


def test_records_match_station_state_at_tick():
    config = small_config()
    sim = Simulation(config, generate_profiles(config, MODELS), warmup_days=1)
    sim.run(ticks=75)
    record = sim.records[-1]
    assert record.tick == 74
    assert record.stations_kw >= 0.0


def test_collect_tick_reads_live_state():
    config = small_config()
    sim = Simulation(config, generate_profiles(config, MODELS), warmup_days=1)
    sim.run(ticks=30)
    record = collect_tick(sim, sim.tick)
    assert record.tick == sim.tick
    assert record.storage_soc == pytest.approx(sim.storage.soc)
    assert record.limit_kw == 200.0


def test_record_without_storage_has_no_soc():
    config = replace(small_config(), storage=None)
    sim = Simulation(config, generate_profiles(config, MODELS), warmup_days=1)
    sim.run(ticks=10)
    assert all(record.storage_soc is None for record in sim.records)
    assert all(record.storage_charge_kw == 0.0 for record in sim.records)


def test_loads_never_negative_and_net_load_within_limit(finished_sim):
    for record in finished_sim.records:
        assert record.stations_kw >= 0.0
        assert not record.is_overloaded
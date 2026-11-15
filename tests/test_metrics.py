from dataclasses import replace
from pathlib import Path

import pytest

from mas.engine import Simulation
from mas.ev_generator import generate_profiles
from mas.ev_models import load_ev_models
from mas.ev_agent import EVState
from mas.grid_agent import GridDecision
from mas.metrics import (
    OVERLOAD_PENALTY_MULT,
    OVERLOAD_TOLERANCE_KW,
    PURCHASE_SHARE,
    TickRecord,
    collect_tick,
    cost_metrics,
    decision_counts,
    load_metrics,
    station_orders,
    summarize,
    vehicle_metrics,
)
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


def test_load_metrics_for_empty_records():
    metrics = load_metrics([])
    assert metrics.peak_load_kw == 0.0
    assert metrics.overload_ticks == 0


def test_load_metrics_peak_mean_and_overload():
    records = [
        make_record(tick=0, station_kw={"st-1": 40.0}),
        make_record(tick=1, station_kw={"st-1": 120.0}),
        make_record(tick=2, station_kw={"st-1": 80.0}),
    ]
    metrics = load_metrics(records)
    assert metrics.peak_load_kw == 120.0
    assert metrics.mean_load_kw == pytest.approx(80.0)
    assert metrics.overload_ticks == 1
    assert metrics.max_overload_kw == 20.0
    assert metrics.overload_kwh == pytest.approx(5.0)


def test_cost_metrics_depend_on_time_of_day():
    night = [make_record(tick=2, station_kw={"st-1": 100.0}, limit_kw=200.0)]
    peak = [make_record(tick=72, station_kw={"st-1": 100.0}, limit_kw=200.0)]
    night_cost, _ = cost_metrics(night, 10.0)
    peak_cost, _ = cost_metrics(peak, 10.0)
    assert night_cost == pytest.approx(100 * 0.25 * 10.0 * PURCHASE_SHARE * 0.85)
    assert peak_cost == pytest.approx(100 * 0.25 * 10.0 * PURCHASE_SHARE * 1.15)
    assert night_cost < peak_cost


def test_cost_metrics_penalize_overload():
    records = [make_record(tick=48, station_kw={"st-1": 120.0}, limit_kw=100.0)]
    purchase, penalty = cost_metrics(records, 10.0)
    assert purchase == pytest.approx(120 * 0.25 * 6.0)
    assert penalty == pytest.approx(20 * 0.25 * 6.0 * OVERLOAD_PENALTY_MULT)


def test_cost_metrics_without_overload_have_no_penalty():
    assert cost_metrics([make_record(tick=48)], 10.0)[1] == 0.0


def test_storage_arbitrage_reduces_purchase_cost():
    plain = [make_record(tick=72, station_kw={"st-1": 100.0}, limit_kw=200.0)]
    with_storage = [make_record(tick=72, station_kw={"st-1": 100.0}, limit_kw=200.0,
                                storage_discharge_kw=40.0)]
    assert cost_metrics(with_storage, 10.0)[0] < cost_metrics(plain, 10.0)[0]


def decision(deficit=False, fallback=False):
    return GridDecision(
        tick=0, substation_limit_kw=100.0, storage_kw=0.0, requested_kw=0.0,
        allocated_kw={}, multipliers={}, deficit=deficit, fallback=fallback,
    )


def test_decision_counts():
    decisions = [decision(), decision(deficit=True), decision(deficit=True, fallback=True)]
    assert decision_counts(decisions) == (2, 1)


def test_station_orders_include_all_kinds(finished_sim):
    total = sum(len(station_orders(station)) for station in finished_sim.stations)
    assert total >= len([ev for ev in finished_sim.evs if ev.state == EVState.DONE])


def test_vehicle_metrics_add_up(finished_sim):
    metrics = vehicle_metrics(finished_sim)
    assert metrics.total == len(finished_sim.evs)
    assert (
        metrics.done + metrics.missed + metrics.no_station + metrics.unfinished
        == metrics.total
    )
    assert metrics.deadline_met == metrics.done
    assert metrics.avg_wait_ticks >= 0.0
    assert metrics.max_wait_ticks >= metrics.avg_wait_ticks


def test_summary_is_consistent_with_agents(finished_sim):
    summary = summarize(finished_sim)
    assert summary.ticks == finished_sim.total_ticks
    assert summary.energy_kwh == pytest.approx(
        sum(station.delivered_kwh for station in finished_sim.stations)
    )
    done_cost = sum(ev.cost_rub for ev in finished_sim.evs if ev.state == EVState.DONE)
    assert summary.revenue_rub >= done_cost - 1e-6
    assert summary.vehicles_total == 30
    assert summary.overload_ticks == 0
    assert summary.storage_final_soc == pytest.approx(finished_sim.storage.soc)


def test_summary_derived_values(finished_sim):
    summary = summarize(finished_sim)
    assert summary.avg_price_rub_per_kwh == pytest.approx(summary.revenue_rub / summary.energy_kwh)
    assert summary.deadline_met_share == pytest.approx(summary.deadline_met / summary.vehicles_total)
    assert summary.operator_cost_rub == pytest.approx(
        summary.purchase_cost_rub + summary.overload_penalty_rub
    )
    assert summary.margin_rub == pytest.approx(summary.revenue_rub - summary.operator_cost_rub)


def test_summary_to_dict_contains_derived_fields(finished_sim):
    data = summarize(finished_sim).to_dict()
    for key in ("energy_kwh", "overload_ticks", "avg_price_rub_per_kwh",
                "deadline_met_share", "operator_cost_rub", "margin_rub"):
        assert key in data


def test_summary_without_storage_has_zero_storage_metrics():
    config = replace(small_config(), storage=None)
    sim = Simulation(config, generate_profiles(config, MODELS), warmup_days=1)
    sim.run()
    summary = summarize(sim)
    assert summary.storage_charged_kwh == 0.0
    assert summary.storage_discharged_kwh == 0.0
    assert summary.storage_final_soc is None


def test_summary_without_vehicles_is_empty():
    config = replace(small_config(), ev_per_day=0)
    sim = Simulation(config, [], warmup_days=1)
    sim.run()
    summary = summarize(sim)
    assert summary.energy_kwh == 0.0
    assert summary.deadline_met_share == 0.0
    assert summary.avg_price_rub_per_kwh == 0.0


def test_station_revenue_accumulates_with_energy():
    config = small_config()
    sim = Simulation(config, generate_profiles(config, MODELS), warmup_days=1)
    sim.run(ticks=60)
    for station in sim.stations:
        if station.delivered_kwh > 0:
            assert station.revenue_rub > 0
            assert 7.0 <= station.revenue_rub / station.delivered_kwh <= 16.0
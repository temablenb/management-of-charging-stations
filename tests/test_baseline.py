from dataclasses import replace
from pathlib import Path

import pytest

from mas.agent import BaseAgent
from mas.baseline import BaselineSimulation, UnlimitedGridAgent
from mas.bus import MessageBus
from mas.engine import Simulation
from mas.ev_agent import EVState
from mas.ev_generator import generate_profiles
from mas.ev_models import load_ev_models
from mas.messages import PowerRequest
from mas.metrics import summarize
from mas.scenario import ScenarioConfig

MODELS = load_ev_models(Path(__file__).resolve().parent.parent / "scenarios" / "ev_models.json")


def small_config(**overrides):
    data = {
        "name": "small", "seed": 3, "days": 1,
        "substation_limit_kw": 120.0, "base_tariff_rub": 10.0,
        "tariff_min_mult": 0.7, "tariff_max_mult": 1.6, "ev_per_day": 60,
        "stations": [
            {"station_id": "st-1", "max_power_kw": 100.0, "connector": "CCS"},
            {"station_id": "st-2", "max_power_kw": 100.0, "connector": "CCS"},
            {"station_id": "st-3", "max_power_kw": 80.0, "connector": "GB/T"},
        ],
        "storage": {"capacity_kwh": 200.0, "max_power_kw": 60.0},
    }
    data.update(overrides)
    return ScenarioConfig.from_dict(data)


def request(sender, demand, max_power=100.0, tick=1):
    return PowerRequest(
        sender=sender, receiver="grid", tick=tick,
        demand_kw=demand, max_power_kw=max_power, forecast_kw=(),
    )


def make_grid(limit=100.0):
    bus = MessageBus()
    grid = UnlimitedGridAgent(bus, limit_kw=limit)
    stations = {sid: BaseAgent(sid, bus) for sid in ("st-1", "st-2")}
    return bus, grid, stations


def collect(bus, grid, stations, demands, tick=1):
    grid.begin_tick(tick)
    for sid, (demand, max_power) in demands.items():
        stations[sid].send(request(sid, demand, max_power, tick))
    bus.deliver()
    grid.process_inbox()


def test_unlimited_grid_gives_everyone_their_demand():
    bus, grid, stations = make_grid(limit=100.0)
    collect(bus, grid, stations, {"st-1": (80.0, 100.0), "st-2": (90.0, 100.0)})
    result = grid.compute_allocation()
    assert result.allocated_kw == {"st-1": 80.0, "st-2": 90.0}
    assert result.deficit


def test_unlimited_grid_caps_demand_by_station_power():
    bus, grid, stations = make_grid(limit=500.0)
    collect(bus, grid, stations, {"st-1": (150.0, 100.0), "st-2": (30.0, 100.0)})
    result = grid.compute_allocation()
    assert result.allocated_kw == {"st-1": 100.0, "st-2": 30.0}
    assert not result.deficit


def test_unlimited_grid_uses_flat_tariff():
    bus, grid, stations = make_grid()
    collect(bus, grid, stations, {"st-1": (80.0, 100.0), "st-2": (90.0, 100.0)})
    assert grid.compute_multipliers(grid.compute_allocation()) == {"st-1": 1.0, "st-2": 1.0}


def test_unlimited_grid_total_can_exceed_limit_in_decisions():
    bus, grid, stations = make_grid(limit=100.0)
    collect(bus, grid, stations, {"st-1": (80.0, 100.0), "st-2": (90.0, 100.0)})
    grid.run_allocation()
    assert grid.decisions[0].total_allocated_kw == pytest.approx(170.0)


def test_baseline_has_no_storage_even_if_scenario_has_one():
    config = small_config()
    assert config.storage is not None
    sim = BaselineSimulation(config, generate_profiles(config, MODELS))
    assert sim.storage is None
    assert sim.config.storage is None


def test_baseline_stations_are_fifo_without_history():
    config = small_config()
    sim = BaselineSimulation(config, generate_profiles(config, MODELS))
    assert all(station.fifo for station in sim.stations)
    assert all(station.hourly_history == [] for station in sim.stations)


def test_baseline_vehicles_do_not_react_to_tariff():
    config = small_config(sensitive_share=1.0)
    profiles = generate_profiles(config, MODELS)
    assert any(profile.price_sensitivity > 0 for profile in profiles)
    sim = BaselineSimulation(config, profiles)
    assert all(ev.profile.price_sensitivity == 0.0 for ev in sim.evs)
    assert not any(ev.delayed for ev in sim.evs)


def test_baseline_and_mas_use_the_same_vehicles():
    config = small_config()
    profiles = generate_profiles(config, MODELS)
    baseline = BaselineSimulation(config, profiles)
    mas = Simulation(config, profiles, warmup_days=1)
    assert [ev.agent_id for ev in baseline.evs] == [ev.agent_id for ev in mas.evs]
    assert [ev.profile.arrival_tick for ev in baseline.evs] == [
        ev.profile.arrival_tick for ev in mas.evs
    ]


@pytest.fixture(scope="module")
def runs():
    config = small_config()
    profiles = generate_profiles(config, MODELS)
    baseline = BaselineSimulation(config, profiles)
    baseline.run()
    mas = Simulation(config, profiles, warmup_days=1)
    mas.run()
    return summarize(baseline), summarize(mas)


def test_baseline_runs_and_serves_vehicles(runs):
    baseline, _ = runs
    assert baseline.vehicles_total == 60
    assert baseline.energy_kwh > 0
    assert baseline.storage_charged_kwh == 0.0
    assert baseline.storage_final_soc is None


def test_baseline_exceeds_limit_while_mas_does_not(runs):
    baseline, mas = runs
    assert baseline.overload_ticks > 0
    assert baseline.max_overload_kw > 0
    assert mas.overload_ticks == 0


def test_baseline_price_is_flat(runs):
    baseline, _ = runs
    assert baseline.avg_price_rub_per_kwh == pytest.approx(10.0)


def test_mas_price_is_higher_than_flat_tariff(runs):
    baseline, mas = runs
    assert mas.avg_price_rub_per_kwh > baseline.avg_price_rub_per_kwh


def test_baseline_pays_overload_penalty_and_mas_does_not(runs):
    baseline, mas = runs
    assert baseline.overload_penalty_rub > 0
    assert mas.overload_penalty_rub == 0.0


def test_baseline_peak_exceeds_limit_and_mas_peak_does_not(runs):
    baseline, mas = runs
    assert baseline.peak_load_kw > 120.0
    assert mas.peak_load_kw <= 120.0 + 1e-3


def test_baseline_run_is_deterministic():
    config = small_config()
    profiles = generate_profiles(config, MODELS)
    first = BaselineSimulation(config, profiles)
    second = BaselineSimulation(config, profiles)
    first.run()
    second.run()
    assert summarize(first) == summarize(second)


def test_baseline_vehicle_states_are_valid():
    config = replace(small_config(), ev_per_day=20)
    sim = BaselineSimulation(config, generate_profiles(config, MODELS))
    sim.run()
    assert all(isinstance(ev.state, EVState) for ev in sim.evs)
    assert sum(1 for ev in sim.evs if ev.state == EVState.DONE) >= 15
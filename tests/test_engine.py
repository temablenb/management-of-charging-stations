from dataclasses import replace
from pathlib import Path

import pytest

from mas.clock import TICKS_PER_DAY
from mas.engine import Simulation
from mas.ev_agent import EVState
from mas.ev_generator import generate_profiles
from mas.ev_models import load_ev_models
from mas.messages import MessageType
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


def make_sim(config=None, warmup_days=1):
    config = config or small_config()
    return Simulation(config, generate_profiles(config, MODELS), warmup_days=warmup_days)


@pytest.fixture(scope="module")
def finished_sim():
    sim = make_sim()
    sim.run()
    return sim


def test_simulation_creates_all_agents():
    sim = make_sim()
    assert [station.agent_id for station in sim.stations] == ["st-1", "st-2", "st-3"]
    assert sim.storage is not None
    assert len(sim.evs) == 30
    assert set(sim.bus.agents) >= {"grid", "storage", "st-1", "st-2", "st-3", "ev-0001"}


def test_no_storage_agent_without_storage_config():
    config = small_config(storage=None)
    assert make_sim(config).storage is None


def test_stations_get_warmup_history():
    sim = make_sim(warmup_days=2)
    assert all(len(station.hourly_history) == 48 for station in sim.stations)


def test_initial_state_and_horizon():
    sim = make_sim(small_config(days=2))
    assert sim.tick == 0
    assert sim.total_ticks == 2 * TICKS_PER_DAY
    assert not sim.finished


def test_step_returns_tick_and_advances_clock():
    sim = make_sim()
    assert sim.step() == 0
    assert sim.step() == 1
    assert sim.tick == 2


def test_one_step_makes_one_grid_decision():
    sim = make_sim()
    sim.step()
    assert len(sim.grid.decisions) == 1
    assert sim.grid.decisions[0].tick == 0


def test_run_stops_after_requested_ticks():
    sim = make_sim()
    sim.run(ticks=10)
    assert sim.tick == 10
    assert not sim.finished
    sim.run(ticks=5)
    assert sim.tick == 15


def test_run_to_the_end_finishes_simulation(finished_sim):
    assert finished_sim.finished
    assert finished_sim.tick == TICKS_PER_DAY
    assert len(finished_sim.grid.decisions) == TICKS_PER_DAY


def test_step_after_end_raises(finished_sim):
    with pytest.raises(RuntimeError):
        finished_sim.step()


def test_every_vehicle_has_a_final_or_active_state(finished_sim):
    assert all(isinstance(ev.state, EVState) for ev in finished_sim.evs)
    done = [ev for ev in finished_sim.evs if ev.state == EVState.DONE]
    assert len(done) >= 25


def test_done_vehicles_received_their_energy(finished_sim):
    for ev in finished_sim.evs:
        if ev.state == EVState.DONE:
            assert ev.delivered_kwh == pytest.approx(ev.profile.needed_kwh, abs=1e-6)
            assert ev.deadline_met


def test_station_energy_matches_vehicle_reports(finished_sim):
    reported = sum(ev.delivered_kwh for ev in finished_sim.evs if ev.state == EVState.DONE)
    delivered = sum(station.delivered_kwh for station in finished_sim.stations)
    assert delivered >= reported - 1e-6


def test_net_substation_load_never_exceeds_limit(finished_sim):
    limit = finished_sim.config.substation_limit_kw
    for decision in finished_sim.grid.decisions:
        assert decision.total_allocated_kw - decision.storage_used_kw <= limit + 1e-3


def test_message_flow_contains_all_message_types(finished_sim):
    counts = finished_sim.bus.count_by_type()
    for message_type in MessageType:
        assert counts.get(message_type, 0) >= 1, message_type


def run_signature(sim):
    """Всё, что должно совпадать у двух одинаковых прогонов."""
    return (
        [(entry.message.type, entry.message.sender, entry.message.receiver, entry.message.tick)
         for entry in sim.bus.journal],
        [(d.tick, d.allocated_kw, d.multipliers) for d in sim.grid.decisions],
        [(ev.state, ev.delivered_kwh, ev.cost_rub, ev.finish_tick) for ev in sim.evs],
        [station.delivered_kwh for station in sim.stations],
    )


def test_same_seed_gives_identical_run():
    first, second = make_sim(), make_sim()
    first.run()
    second.run()
    assert run_signature(first) == run_signature(second)


def test_different_seed_gives_different_run():
    first = make_sim(small_config(seed=3))
    second = make_sim(small_config(seed=4))
    first.run()
    second.run()
    assert run_signature(first) != run_signature(second)


def test_stepwise_run_equals_single_run():
    stepwise = make_sim()
    for _ in range(stepwise.total_ticks):
        stepwise.step()
    stepwise.finalize()
    single = make_sim()
    single.run()
    assert run_signature(stepwise) == run_signature(single)


def test_run_more_ticks_than_remaining_stops_at_end():
    sim = make_sim()
    sim.run(ticks=10_000)
    assert sim.finished
    assert sim.tick == TICKS_PER_DAY


def test_run_rejects_negative_tick_count():
    with pytest.raises(ValueError):
        make_sim().run(ticks=-1)


def test_finalize_delivers_last_reports():
    config = small_config(ev_per_day=0)
    sim = Simulation(config, [], warmup_days=1)
    sim.run(ticks=5)
    assert sim.bus.pending_count == 0


def test_simulation_without_vehicles_has_no_charging():
    config = replace(small_config(), ev_per_day=0)
    sim = Simulation(config, [], warmup_days=1)
    sim.run()
    assert sum(station.delivered_kwh for station in sim.stations) == 0
    assert all(d.requested_kw <= sim.storage.config.max_power_kw for d in sim.grid.decisions)
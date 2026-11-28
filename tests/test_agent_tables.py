import pytest

from mas.cli import DEFAULT_MODELS_PATH, apply_overrides, run_scenario
from mas.ev_models import load_ev_models
from ui.agent_tables import DECISION_COLUMNS, VEHICLE_COLUMNS, decisions_frame, vehicles_frame
from ui.scenarios import load_by_name

CONFIG = apply_overrides(load_by_name("default"), days=1, ev_per_day=15)


@pytest.fixture(scope="module")
def sim():
    simulation, _ = run_scenario(CONFIG, load_ev_models(DEFAULT_MODELS_PATH), warmup_days=1)
    return simulation


def test_decisions_frame_has_row_per_decision(sim):
    frame = decisions_frame(sim)
    assert len(frame) == len(sim.grid.decisions)
    assert list(frame.columns) == DECISION_COLUMNS
    assert frame["tick"].is_monotonic_increasing


def test_vehicles_frame_has_row_per_vehicle(sim):
    frame = vehicles_frame(sim)
    assert len(frame) == len(sim.evs)
    assert list(frame.columns) == VEHICLE_COLUMNS
    assert frame["ev"].is_unique


def test_vehicle_states_are_text(sim):
    assert all(isinstance(state, str) for state in vehicles_frame(sim)["state"])
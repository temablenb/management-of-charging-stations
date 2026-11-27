import pytest

from mas.cli import DEFAULT_MODELS_PATH, apply_overrides
from mas.ev_models import load_ev_models
from mas.runs import save_run
from ui.run_view import RunView
from ui.runs_store import save_pair, saved_keys
from ui.scenarios import load_by_name
from ui.sim_runner import run_pair

MODELS = load_ev_models(DEFAULT_MODELS_PATH)
CONFIG = apply_overrides(load_by_name("default"), days=1, ev_per_day=15)


@pytest.fixture(scope="module")
def view():
    comparison, mas, baseline = run_pair(CONFIG, MODELS, warmup_days=1)
    return RunView.from_live(comparison, mas, baseline)


def test_save_pair_writes_both_files(tmp_path, view):
    paths = save_pair(view, tmp_path)
    assert len(paths) == 2 and all(path.exists() for path in paths)


def test_saved_keys_lists_parameters(tmp_path, view):
    save_pair(view, tmp_path)
    assert saved_keys(tmp_path) == [(view.scenario, view.seed, view.days)]


def test_saved_keys_of_missing_directory_is_empty(tmp_path):
    assert saved_keys(tmp_path / "нет") == []


def test_roundtrip_restores_comparison_and_records(tmp_path, view):
    save_pair(view, tmp_path)
    restored = RunView.from_saved(tmp_path, view.scenario, view.seed, view.days)
    assert restored.comparison.to_dict() == view.comparison.to_dict()
    assert len(restored.mas_records) == len(view.mas_records)
    assert restored.mas_sim is None and restored.baseline_sim is None


def test_from_saved_requires_both_modes(tmp_path, view):
    save_run(tmp_path, "mas", view.scenario, view.seed, view.days,
             view.comparison.mas, view.mas_records)
    with pytest.raises(ValueError):
        RunView.from_saved(tmp_path, view.scenario, view.seed, view.days)
import pytest

from mas.cli import DEFAULT_MODELS_PATH, apply_overrides
from mas.comparison import run_comparison
from mas.ev_models import load_ev_models
from ui.scenarios import load_by_name
from ui.sim_runner import run_pair

MODELS = load_ev_models(DEFAULT_MODELS_PATH)
CONFIG = apply_overrides(load_by_name("default"), days=1, ev_per_day=15)


def test_progress_grows_to_one_and_names_both_runs():
    calls = []
    run_pair(CONFIG, MODELS, warmup_days=1, progress=lambda share, label: calls.append((share, label)))
    shares = [share for share, _ in calls]
    assert shares == sorted(shares)
    assert shares[-1] == pytest.approx(1.0)
    assert {label for _, label in calls} == {"Базовый сценарий", "Мультиагентная система"}


def test_result_matches_run_comparison():
    comparison, _, _ = run_pair(CONFIG, MODELS, warmup_days=1)
    reference, _, _ = run_comparison(CONFIG, MODELS, warmup_days=1)
    assert comparison.to_dict() == reference.to_dict()


def test_simulations_are_finished():
    _, mas, baseline = run_pair(CONFIG, MODELS, warmup_days=1)
    assert mas.finished and baseline.finished
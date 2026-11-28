import pytest

from mas.cli import DEFAULT_MODELS_PATH, apply_overrides
from mas.comparison import METRICS, format_value, run_comparison
from mas.ev_models import load_ev_models
from ui.comparison_view import VERDICT_LABELS, comparison_frame
from ui.scenarios import load_by_name

CONFIG = apply_overrides(load_by_name("default"), days=1, ev_per_day=15)


@pytest.fixture(scope="module")
def comparison():
    result, _, _ = run_comparison(CONFIG, load_ev_models(DEFAULT_MODELS_PATH), warmup_days=1)
    return result


def test_frame_has_row_per_metric(comparison):
    frame = comparison_frame(comparison)
    assert len(frame) == len(METRICS)
    assert list(frame.columns) == ["Показатель", "Базовый", "Мультиагентная", "Изменение", "Итог"]


def test_verdicts_are_known_labels(comparison):
    assert set(comparison_frame(comparison)["Итог"]) <= set(VERDICT_LABELS.values())


def test_values_are_formatted_like_console_report(comparison):
    row = comparison.rows()[0]
    frame = comparison_frame(comparison)
    assert frame["Базовый"].iloc[0] == format_value(row.spec, row.baseline)
    assert frame["Мультиагентная"].iloc[0] == format_value(row.spec, row.mas)
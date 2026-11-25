from dataclasses import fields, replace
from pathlib import Path

import pytest

from mas.comparison import (
    BETTER,
    EQUAL,
    METRICS,
    NEUTRAL,
    WORSE,
    Comparison,
    ComparisonRow,
    MetricSpec,
    format_comparison,
    format_delta,
    format_value,
    run_comparison,
)
from mas.ev_models import load_ev_models
from mas.metrics import RunSummary
from mas.scenario import ScenarioConfig

MODELS = load_ev_models(Path(__file__).resolve().parent.parent / "scenarios" / "ev_models.json")


def make_summary(**overrides):
    values = {item.name: 0 for item in fields(RunSummary)}
    values["storage_final_soc"] = None
    values.update(overrides)
    return RunSummary(**values)


def small_config(**overrides):
    data = {
        "name": "small", "seed": 3, "days": 1,
        "substation_limit_kw": 120.0, "base_tariff_rub": 10.0,
        "tariff_min_mult": 0.7, "tariff_max_mult": 1.6, "ev_per_day": 40,
        "stations": [
            {"station_id": "st-1", "max_power_kw": 100.0, "connector": "CCS"},
            {"station_id": "st-2", "max_power_kw": 100.0, "connector": "CCS"},
            {"station_id": "st-3", "max_power_kw": 80.0, "connector": "GB/T"},
        ],
        "storage": {"capacity_kwh": 200.0, "max_power_kw": 60.0},
    }
    data.update(overrides)
    return ScenarioConfig.from_dict(data)


def row(lower_is_better, baseline, mas, decimals=0, unit="руб"):
    spec = MetricSpec("x", "Показатель", unit, lower_is_better, decimals)
    return ComparisonRow(spec, baseline, mas)


def test_delta_and_percent():
    item = row(True, 200.0, 150.0)
    assert item.delta == -50.0
    assert item.delta_pct == pytest.approx(-25.0)


def test_percent_is_none_for_zero_baseline():
    item = row(True, 0.0, 5.0)
    assert item.delta == 5.0
    assert item.delta_pct is None


def test_verdict_for_lower_is_better():
    assert row(True, 10.0, 5.0).verdict == BETTER
    assert row(True, 10.0, 15.0).verdict == WORSE


def test_verdict_for_higher_is_better():
    assert row(False, 10.0, 15.0).verdict == BETTER
    assert row(False, 10.0, 5.0).verdict == WORSE


def test_verdict_equal_and_neutral():
    assert row(True, 10.0, 10.0).verdict == EQUAL
    assert row(None, 10.0, 99.0).verdict == NEUTRAL


def test_metric_keys_exist_in_summary_and_are_unique():
    summary = make_summary()
    keys = [spec.key for spec in METRICS]
    assert len(set(keys)) == len(keys)
    for key in keys:
        assert hasattr(summary, key)


def test_rows_follow_metric_order():
    comparison = Comparison("s", 1, 1, make_summary(), make_summary())
    assert [item.spec.key for item in comparison.rows()] == [spec.key for spec in METRICS]


def test_rows_take_values_from_both_summaries():
    comparison = Comparison(
        "s", 1, 1,
        make_summary(overload_ticks=12, vehicles_total=10, deadline_met=10),
        make_summary(overload_ticks=0, vehicles_total=10, deadline_met=9),
    )
    rows = {item.spec.key: item for item in comparison.rows()}
    assert rows["overload_ticks"].baseline == 12 and rows["overload_ticks"].mas == 0
    assert rows["overload_ticks"].verdict == BETTER
    assert rows["deadline_met_share"].baseline == 1.0
    assert rows["deadline_met_share"].mas == pytest.approx(0.9)
    assert rows["deadline_met_share"].verdict == WORSE


def test_format_value_percent_and_decimals():
    assert format_value(MetricSpec("a", "A", "%", False, 1), 0.9667) == "96.7"
    assert format_value(MetricSpec("a", "A", "руб", True, 0), 1234.56) == "1235"
    assert format_value(MetricSpec("a", "A", "руб/кВт·ч", True, 2), 14.9677) == "14.97"


def test_format_delta_variants():
    assert format_delta(row(True, 200.0, 150.0)) == "-25.0% лучше"
    assert format_delta(row(True, 100.0, 120.0)) == "+20.0% хуже"
    assert format_delta(row(True, 0.0, 5.0)) == "+5 хуже"
    assert format_delta(row(True, 10.0, 10.0)) == "0 без изменений"
    assert format_delta(row(None, 100.0, 150.0)) == "+50.0%"


def test_to_dict_has_rows_and_summaries():
    comparison = Comparison("s", 7, 2, make_summary(energy_kwh=5.0), make_summary(energy_kwh=6.0))
    data = comparison.to_dict()
    assert (data["scenario"], data["seed"], data["days"]) == ("s", 7, 2)
    assert data["baseline"]["energy_kwh"] == 5.0
    assert len(data["rows"]) == len(METRICS)
    energy = next(item for item in data["rows"] if item["key"] == "energy_kwh")
    assert energy["delta"] == 1.0 and energy["verdict"] == BETTER


@pytest.fixture(scope="module")
def compared():
    return run_comparison(small_config(), MODELS, warmup_days=1)


def test_run_comparison_returns_both_simulations(compared):
    comparison, mas, baseline = compared
    assert mas.finished and baseline.finished
    assert baseline.storage is None and mas.storage is not None
    assert comparison.scenario == "small"


def test_comparison_uses_same_vehicle_flow(compared):
    comparison, _, _ = compared
    assert comparison.baseline.vehicles_total == comparison.mas.vehicles_total == 40


def test_comparison_shows_overload_only_in_baseline(compared):
    comparison, _, _ = compared
    assert comparison.baseline.overload_ticks > 0
    assert comparison.mas.overload_ticks == 0
    rows = {item.spec.key: item for item in comparison.rows()}
    assert rows["overload_ticks"].verdict == BETTER
    assert rows["operator_cost_rub"].verdict == BETTER
    assert rows["avg_price_rub_per_kwh"].verdict == WORSE


def test_format_comparison_contains_table(compared):
    comparison, _, _ = compared
    text = format_comparison(comparison)
    lines = text.splitlines()
    assert lines[0].startswith("Сравнение: small (1 сут., seed 3)")
    assert "Показатель" in lines[1] and "Базовый" in lines[1] and "MAS" in lines[1]
    assert len(lines) == 2 + len(METRICS)
    assert any("Затраты оператора" in line for line in lines)


def test_comparison_is_reproducible():
    first = run_comparison(replace(small_config(), ev_per_day=15), MODELS, warmup_days=1)[0]
    second = run_comparison(replace(small_config(), ev_per_day=15), MODELS, warmup_days=1)[0]
    assert first == second
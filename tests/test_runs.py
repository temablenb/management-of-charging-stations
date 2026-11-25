import json
from dataclasses import fields
from pathlib import Path

import pytest

from mas.comparison import run_comparison
from mas.ev_models import load_ev_models
from mas.metrics import RunSummary, TickRecord
from mas.runs import list_runs, load_run, run_filename, save_run
from mas.scenario import ScenarioConfig

MODELS = load_ev_models(Path(__file__).resolve().parent.parent / "scenarios" / "ev_models.json")


def small_config():
    return ScenarioConfig.from_dict({
        "name": "small", "seed": 3, "days": 1,
        "substation_limit_kw": 120.0, "base_tariff_rub": 10.0,
        "tariff_min_mult": 0.7, "tariff_max_mult": 1.6, "ev_per_day": 15,
        "stations": [
            {"station_id": "st-1", "max_power_kw": 100.0, "connector": "CCS"},
            {"station_id": "st-2", "max_power_kw": 100.0, "connector": "CCS"},
            {"station_id": "st-3", "max_power_kw": 80.0, "connector": "GB/T"},
        ],
        "storage": {"capacity_kwh": 200.0, "max_power_kw": 60.0},
    })


@pytest.fixture(scope="module")
def compared():
    return run_comparison(small_config(), MODELS, warmup_days=1)


def test_filename_contains_all_parameters():
    assert run_filename("evening_peak", "mas", 43, 7) == "evening_peak_mas_s43_d7.json"
    assert run_filename("default", "baseline", 42, 1) == "default_baseline_s42_d1.json"


def test_filename_rejects_unknown_mode():
    with pytest.raises(ValueError):
        run_filename("default", "other", 1, 1)


def test_summary_from_dict_ignores_derived_fields(compared):
    comparison, _, _ = compared
    restored = RunSummary.from_dict(comparison.mas.to_dict())
    assert restored == comparison.mas
    assert {item.name for item in fields(RunSummary)} <= set(comparison.mas.to_dict())


def test_save_creates_directory_and_file(tmp_path, compared):
    comparison, mas, _ = compared
    target = save_run(tmp_path / "nested" / "runs", "mas", "small", 3, 1, comparison.mas, mas.records)
    assert target.exists()
    assert target.name == "small_mas_s3_d1.json"


def test_roundtrip_restores_summary_and_records(tmp_path, compared):
    comparison, mas, _ = compared
    target = save_run(tmp_path, "mas", "small", 3, 1, comparison.mas, mas.records)
    saved = load_run(target)
    assert saved.mode == "mas"
    assert (saved.scenario, saved.seed, saved.days) == ("small", 3, 1)
    assert saved.summary == comparison.mas
    assert saved.records == mas.records
    assert all(isinstance(record, TickRecord) for record in saved.records)


def test_baseline_roundtrip_has_no_soc(tmp_path, compared):
    comparison, _, baseline = compared
    target = save_run(tmp_path, "baseline", "small", 3, 1, comparison.baseline, baseline.records)
    saved = load_run(target)
    assert saved.records == baseline.records
    assert all(record.storage_soc is None for record in saved.records)


def test_saving_again_overwrites_same_file(tmp_path, compared):
    comparison, mas, _ = compared
    first = save_run(tmp_path, "mas", "small", 3, 1, comparison.mas, mas.records)
    second = save_run(tmp_path, "mas", "small", 3, 1, comparison.mas, mas.records)
    assert first == second
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_load_rejects_unknown_format(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": 99}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_run(bad)


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_run(tmp_path / "no.json")


def test_list_runs_returns_sorted_infos(tmp_path, compared):
    comparison, mas, baseline = compared
    save_run(tmp_path, "mas", "small", 3, 1, comparison.mas, mas.records)
    save_run(tmp_path, "baseline", "small", 3, 1, comparison.baseline, baseline.records)
    infos = list_runs(tmp_path)
    assert [(info.mode, info.scenario, info.seed, info.days) for info in infos] == [
        ("baseline", "small", 3, 1), ("mas", "small", 3, 1),
    ]
    assert infos[0].path.name == "small_baseline_s3_d1.json"


def test_list_runs_skips_foreign_and_broken_files(tmp_path, compared):
    comparison, mas, _ = compared
    save_run(tmp_path, "mas", "small", 3, 1, comparison.mas, mas.records)
    (tmp_path / "notes.json").write_text(json.dumps({"hello": 1}), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert len(list_runs(tmp_path)) == 1


def test_list_runs_of_missing_directory_is_empty(tmp_path):
    assert list_runs(tmp_path / "nowhere") == []
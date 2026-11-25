import json
from pathlib import Path

import pytest

from mas.baseline import BaselineSimulation
from mas.cli import (
    apply_overrides,
    build_parser,
    format_summary,
    main,
    run_baseline,
    run_scenario,
)
from mas.engine import Simulation
from mas.ev_models import load_ev_models
from mas.metrics import RunSummary
from mas.runs import list_runs, load_run
from mas.scenario import load_scenario

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "scenarios"
MODELS = load_ev_models(SCENARIOS / "ev_models.json")
NAMES = ("default", "evening_peak", "reduced_limit", "many_ev")
SMALL = ["--days", "1", "--ev-per-day", "15", "--warmup-days", "1"]


def scenario(name):
    return load_scenario(SCENARIOS / f"{name}.json")


@pytest.mark.parametrize("name", NAMES)
def test_scenario_files_load(name):
    config = scenario(name)
    assert config.name == name
    assert config.days == 7
    assert len(config.stations) == 7
    assert config.storage is not None


def test_scenarios_differ_in_the_intended_way():
    default, evening, reduced, many = (scenario(name) for name in NAMES)
    assert evening.ev_per_day > default.ev_per_day
    assert reduced.substation_limit_kw < default.substation_limit_kw
    assert many.ev_per_day > evening.ev_per_day
    assert len({default.seed, evening.seed, reduced.seed, many.seed}) == 4


def test_overrides_without_arguments_keep_config():
    config = scenario("default")
    assert apply_overrides(config) == config


def test_overrides_change_selected_fields():
    config = apply_overrides(
        scenario("default"), days=2, seed=9, ev_per_day=40, limit_kw=300.0
    )
    assert (config.days, config.seed, config.ev_per_day) == (2, 9, 40)
    assert config.substation_limit_kw == 300.0
    assert config.storage is not None


def test_overrides_can_remove_storage():
    assert apply_overrides(scenario("default"), no_storage=True).storage is None


def test_overrides_are_validated():
    with pytest.raises(ValueError):
        apply_overrides(scenario("default"), days=0)
    with pytest.raises(ValueError):
        apply_overrides(scenario("default"), limit_kw=-5.0)


def test_run_scenario_returns_simulation_and_summary():
    config = apply_overrides(scenario("default"), days=1, ev_per_day=15)
    simulation, summary = run_scenario(config, MODELS, warmup_days=1)
    assert isinstance(simulation, Simulation)
    assert isinstance(summary, RunSummary)
    assert simulation.finished
    assert summary.vehicles_total == 15


def test_format_summary_mentions_main_metrics():
    config = apply_overrides(scenario("default"), days=1, ev_per_day=15)
    _, summary = run_scenario(config, MODELS, warmup_days=1)
    text = format_summary(config, summary)
    for fragment in ("Сценарий: default", "Лимит подстанции: 420 кВт", "Затраты оператора",
                     "Пиковая нагрузка", "Автомобили: 15", "Накопитель: заряжено"):
        assert fragment in text


def test_format_summary_without_storage_has_no_storage_line():
    config = apply_overrides(scenario("default"), days=1, ev_per_day=15, no_storage=True)
    _, summary = run_scenario(config, MODELS, warmup_days=1)
    text = format_summary(config, summary)
    assert "накопитель: нет" in text
    assert "Накопитель: заряжено" not in text


def test_parser_defaults():
    args = build_parser().parse_args(["scenarios/default.json"])
    assert args.scenario == "scenarios/default.json"
    assert args.days is None and args.seed is None
    assert args.warmup_days == 3
    assert not args.no_storage
    assert args.json_path is None


def test_parser_reads_options():
    args = build_parser().parse_args(
        ["x.json", "--days", "2", "--seed", "5", "--ev-per-day", "9", "--limit", "300",
         "--no-storage", "--json", "out.json"]
    )
    assert (args.days, args.seed, args.ev_per_day, args.limit) == (2, 5, 9, 300.0)
    assert args.no_storage
    assert args.json_path == "out.json"


def test_main_prints_summary(capsys):
    code = main([str(SCENARIOS / "default.json")] + SMALL)
    output = capsys.readouterr().out
    assert code == 0
    assert "Сценарий: default (1 сут., seed 42)" in output


def test_main_writes_json(tmp_path, capsys):
    target = tmp_path / "result.json"
    code = main([str(SCENARIOS / "default.json")] + SMALL + ["--json", str(target)])
    capsys.readouterr()
    assert code == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["scenario"] == "default"
    assert payload["summary"]["vehicles_total"] == 15
    assert "operator_cost_rub" in payload["summary"]


def test_main_reports_missing_file(tmp_path, capsys):
    code = main([str(tmp_path / "no.json")])
    captured = capsys.readouterr()
    assert code == 2
    assert "Ошибка" in captured.err


def test_main_reports_invalid_parameters(capsys):
    code = main([str(SCENARIOS / "default.json"), "--days", "0"])
    captured = capsys.readouterr()
    assert code == 2
    assert "хотя бы одни сутки" in captured.err


def test_main_is_reproducible(capsys):
    main([str(SCENARIOS / "default.json")] + SMALL)
    first = capsys.readouterr().out
    main([str(SCENARIOS / "default.json")] + SMALL)
    second = capsys.readouterr().out
    assert first == second


def test_parser_new_options_have_defaults():
    args = build_parser().parse_args(["scenarios/default.json"])
    assert not args.baseline and not args.compare
    assert args.save_dir is None


def test_parser_reads_new_options():
    args = build_parser().parse_args(["x.json", "--compare", "--save", "runs"])
    assert args.compare and not args.baseline
    assert args.save_dir == "runs"


def test_baseline_and_compare_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["x.json", "--baseline", "--compare"])
    assert error.value.code == 2
    assert "not allowed" in capsys.readouterr().err


def test_run_baseline_returns_baseline_simulation_and_summary():
    config = apply_overrides(scenario("default"), days=1, ev_per_day=15)
    simulation, summary = run_baseline(config, MODELS)
    assert isinstance(simulation, BaselineSimulation)
    assert isinstance(summary, RunSummary)
    assert simulation.storage is None
    assert summary.vehicles_total == 15


def test_format_summary_baseline_mentions_mode():
    config = apply_overrides(scenario("default"), days=1, ev_per_day=15)
    simulation, summary = run_baseline(config, MODELS)
    text = format_summary(simulation.config, summary, mode="baseline")
    assert "Режим: базовый" in text
    assert "накопитель: нет" in text


def test_format_summary_default_mode_has_no_mode_line():
    config = apply_overrides(scenario("default"), days=1, ev_per_day=15)
    _, summary = run_scenario(config, MODELS, warmup_days=1)
    assert "Режим:" not in format_summary(config, summary)


def test_main_baseline_prints_mode(capsys):
    code = main([str(SCENARIOS / "default.json"), "--baseline"] + SMALL)
    output = capsys.readouterr().out
    assert code == 0
    assert "Режим: базовый" in output


def test_main_compare_prints_table(capsys):
    code = main([str(SCENARIOS / "default.json"), "--compare"] + SMALL)
    output = capsys.readouterr().out
    assert code == 0
    assert "Сравнение: default (1 сут., seed 42)" in output
    assert "Затраты оператора" in output and "Изменение MAS" in output


def test_main_compare_writes_comparison_json(tmp_path, capsys):
    target = tmp_path / "cmp.json"
    code = main([str(SCENARIOS / "default.json"), "--compare"] + SMALL + ["--json", str(target)])
    capsys.readouterr()
    assert code == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["scenario"] == "default"
    assert "baseline" in payload and "mas" in payload and payload["rows"]


def test_main_single_run_json_has_mode(tmp_path, capsys):
    target = tmp_path / "one.json"
    main([str(SCENARIOS / "default.json"), "--baseline"] + SMALL + ["--json", str(target)])
    capsys.readouterr()
    assert json.loads(target.read_text(encoding="utf-8"))["mode"] == "baseline"


def test_main_save_stores_single_run(tmp_path, capsys):
    code = main([str(SCENARIOS / "default.json")] + SMALL + ["--save", str(tmp_path)])
    output = capsys.readouterr().out
    assert code == 0
    assert "Прогон сохранён:" in output
    infos = list_runs(tmp_path)
    assert [(info.mode, info.scenario, info.days) for info in infos] == [("mas", "default", 1)]


def test_main_compare_save_stores_both_runs(tmp_path, capsys):
    main([str(SCENARIOS / "default.json"), "--compare"] + SMALL + ["--save", str(tmp_path)])
    capsys.readouterr()
    infos = list_runs(tmp_path)
    assert {info.mode for info in infos} == {"mas", "baseline"}
    saved = load_run(next(info.path for info in infos if info.mode == "mas"))
    assert len(saved.records) == 96
    assert saved.summary.vehicles_total == 15
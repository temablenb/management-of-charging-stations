"""Запуск симуляции из командной строки.

Пример: python -m mas.cli scenarios/evening_peak.json --days 2 --json result.json
"""
from dataclasses import replace
import argparse
import json
import sys
from pathlib import Path

from mas.baseline import BaselineSimulation
from mas.engine import DEFAULT_WARMUP_DAYS, Simulation
from mas.ev_generator import generate_profiles
from mas.ev_models import load_ev_models
from mas.metrics import RunSummary, summarize
from mas.scenario import ScenarioConfig, load_scenario
from mas.comparison import format_comparison, run_comparison
from mas.runs import save_run

DEFAULT_MODELS_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "ev_models.json"


def apply_overrides(
    config: ScenarioConfig,
    *,
    days: int | None = None,
    seed: int | None = None,
    ev_per_day: int | None = None,
    limit_kw: float | None = None,
    no_storage: bool = False,
) -> ScenarioConfig:
    """Меняет параметры сценария, заданные в командной строке (проверки сработают заново)."""
    changes = {}
    if days is not None:
        changes["days"] = days
    if seed is not None:
        changes["seed"] = seed
    if ev_per_day is not None:
        changes["ev_per_day"] = ev_per_day
    if limit_kw is not None:
        changes["substation_limit_kw"] = limit_kw
    if no_storage:
        changes["storage"] = None
    return replace(config, **changes)


def run_scenario(
    config: ScenarioConfig,
    models,
    warmup_days: int = DEFAULT_WARMUP_DAYS,
) -> tuple[Simulation, RunSummary]:
    """Генерирует поток автомобилей, прогоняет мультиагентную симуляцию и считает итоги."""
    profiles = generate_profiles(config, models)
    simulation = Simulation(config, profiles, warmup_days=warmup_days)
    simulation.run()
    return simulation, summarize(simulation)


def run_baseline(
    config: ScenarioConfig, models
) -> tuple[BaselineSimulation, RunSummary]:
    """Прогоняет базовый сценарий (без координации агентов) на том же потоке автомобилей."""
    profiles = generate_profiles(config, models)
    simulation = BaselineSimulation(config, profiles)
    simulation.run()
    return simulation, summarize(simulation)


def format_summary(config: ScenarioConfig, summary: RunSummary, mode: str = "mas") -> str:
    """Итоги прогона в виде текста для консоли."""
    storage = "есть" if config.storage else "нет"
    lines = [f"Сценарий: {config.name} ({config.days} сут., seed {config.seed})"]
    if mode == "baseline":
        lines.append("Режим: базовый (без координации агентов, плоский тариф, очередь по приезду)")
    lines += [
        f"Сценарий: {config.name} ({config.days} сут., seed {config.seed})",
        f"Лимит подстанции: {config.substation_limit_kw:.0f} кВт, накопитель: {storage}",
        f"Выдано энергии: {summary.energy_kwh:.1f} кВт·ч",
        f"Выручка от водителей: {summary.revenue_rub:.0f} руб "
        f"(средняя цена {summary.avg_price_rub_per_kwh:.2f} руб/кВт·ч)",
        f"Затраты оператора: {summary.operator_cost_rub:.0f} руб "
        f"(закупка {summary.purchase_cost_rub:.0f}, штраф {summary.overload_penalty_rub:.0f})",
        f"Пиковая нагрузка: {summary.peak_load_kw:.1f} кВт, "
        f"превышений лимита: {summary.overload_ticks} тактов "
        f"(максимум {summary.max_overload_kw:.1f} кВт)",
        f"Тактов дефицита мощности: {summary.deficit_ticks} "
        f"(запасной вариант: {summary.fallback_ticks})",
        f"Автомобили: {summary.vehicles_total}, успели к дедлайну "
        f"{summary.deadline_met} ({summary.deadline_met_share:.1%}), "
        f"опоздали {summary.missed}, без станции {summary.no_station}, "
        f"не завершены к концу {summary.unfinished}",
        f"Ожидание в очереди: в среднем {summary.avg_wait_ticks:.2f} такта, "
        f"максимум {summary.max_wait_ticks} тактов, одновременно ждали до {summary.max_waiting}",
    ]
    if config.storage:
        lines.append(
            f"Накопитель: заряжено {summary.storage_charged_kwh:.1f} кВт·ч, "
            f"отдано {summary.storage_discharged_kwh:.1f} кВт·ч, "
            f"заряд в конце {summary.storage_final_soc:.0%}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mas.cli",
        description="Мультиагентная симуляция сети зарядных станций.",
    )
    parser.add_argument("scenario", help="путь к JSON-файлу сценария")
    parser.add_argument("--days", type=int, help="число суток вместо указанного в сценарии")
    parser.add_argument("--seed", type=int, help="seed вместо указанного в сценарии")
    parser.add_argument("--ev-per-day", type=int, help="число автомобилей в сутки")
    parser.add_argument("--limit", type=float, help="лимит подстанции, кВт")
    parser.add_argument("--no-storage", action="store_true", help="убрать накопитель")
    parser.add_argument("--warmup-days", type=int, default=DEFAULT_WARMUP_DAYS,
                        help="суток предыстории для прогноза (по умолчанию 3)")
    parser.add_argument("--models", default=str(DEFAULT_MODELS_PATH),
                        help="каталог моделей электромобилей (JSON)")
    parser.add_argument("--json", dest="json_path", help="сохранить итоги в JSON-файл")
    parser.add_argument("--save", dest="save_dir", metavar="ПАПКА",
                        help="сохранить прогоны (итоги и состояние по тактам) в папку")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--baseline", action="store_true",
                      help="запустить только базовый сценарий")
    mode.add_argument("--compare", action="store_true",
                      help="запустить оба сценария и вывести таблицу сравнения")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = apply_overrides(
            load_scenario(args.scenario),
            days=args.days, seed=args.seed, ev_per_day=args.ev_per_day,
            limit_kw=args.limit, no_storage=args.no_storage,
        )
        models = load_ev_models(args.models)
        if args.compare:
            comparison, mas_sim, baseline_sim = run_comparison(
                config, models, warmup_days=args.warmup_days
            )
            print(format_comparison(comparison))
            payload = comparison.to_dict()
            saved = [("mas", comparison.mas, mas_sim), ("baseline", comparison.baseline, baseline_sim)]
        elif args.baseline:
            simulation, summary = run_baseline(config, models)
            print(format_summary(simulation.config, summary, mode="baseline"))
            payload = {"scenario": config.name, "seed": config.seed, "days": config.days,
                       "mode": "baseline", "summary": summary.to_dict()}
            saved = [("baseline", summary, simulation)]
        else:
            simulation, summary = run_scenario(config, models, warmup_days=args.warmup_days)
            print(format_summary(config, summary))
            payload = {"scenario": config.name, "seed": config.seed, "days": config.days,
                       "mode": "mas", "summary": summary.to_dict()}
            saved = [("mas", summary, simulation)]
        if args.save_dir:
            for mode, summary, simulation in saved:
                path = save_run(args.save_dir, mode, config.name, config.seed, config.days,
                                summary, simulation.records)
                print(f"Прогон сохранён: {path}")
        if args.json_path:
            Path(args.json_path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except (OSError, ValueError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
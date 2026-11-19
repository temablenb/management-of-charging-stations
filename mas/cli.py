"""Запуск симуляции из командной строки.

Пример: python -m mas.cli scenarios/evening_peak.json --days 2 --json result.json
"""
from dataclasses import replace
from pathlib import Path

from mas.engine import DEFAULT_WARMUP_DAYS, Simulation
from mas.ev_generator import generate_profiles
from mas.ev_models import load_ev_models
from mas.metrics import RunSummary, summarize
from mas.scenario import ScenarioConfig, load_scenario

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


def format_summary(config: ScenarioConfig, summary: RunSummary) -> str:
    """Итоги прогона в виде текста для консоли."""
    storage = "есть" if config.storage else "нет"
    lines = [
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
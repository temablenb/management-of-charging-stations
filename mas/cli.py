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
"""Список сценариев для дашборда."""

from pathlib import Path

from mas.scenario import ScenarioConfig, load_scenario

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


def available_scenarios() -> dict[str, Path]:
    """Имя файла без расширения -> путь (справочник моделей автомобилей не сценарий)."""
    return {
        path.stem: path
        for path in sorted(SCENARIOS_DIR.glob("*.json"))
        if path.stem != "ev_models"
    }


def load_by_name(name: str) -> ScenarioConfig:
    paths = available_scenarios()
    if name not in paths:
        raise KeyError(f"Неизвестный сценарий: {name}")
    return load_scenario(paths[name])
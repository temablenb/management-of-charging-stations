"""Папка с сохранёнными прогонами дашборда."""

from pathlib import Path

from mas.runs import DEFAULT_RUNS_DIR, list_runs, save_run
from ui.run_view import RunView

RUNS_DIR = Path(__file__).resolve().parent.parent / DEFAULT_RUNS_DIR


def save_pair(view: RunView, directory=RUNS_DIR) -> list[Path]:
    """Сохраняет оба прогона (мультиагентный и базовый), возвращает пути файлов."""
    return [
        save_run(directory, "mas", view.scenario, view.seed, view.days,
                 view.comparison.mas, view.mas_records),
        save_run(directory, "baseline", view.scenario, view.seed, view.days,
                 view.comparison.baseline, view.baseline_records),
    ]


def saved_keys(directory=RUNS_DIR) -> list[tuple[str, int, int]]:
    """Сценарий, seed и число суток сохранённых прогонов."""
    return sorted({(info.scenario, info.seed, info.days) for info in list_runs(directory)})
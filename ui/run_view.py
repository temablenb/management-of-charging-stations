"""Данные прогона для страницы «Симуляция»: живые симуляции или сохранённые файлы."""

from dataclasses import dataclass
from pathlib import Path

from mas.baseline import BaselineSimulation
from mas.comparison import Comparison
from mas.engine import Simulation
from mas.metrics import TickRecord
from mas.runs import MODES, load_run, run_filename


@dataclass(frozen=True)
class RunView:
    """Пара прогонов (мультиагентный и базовый) для показа на странице."""

    scenario: str
    seed: int
    days: int
    comparison: Comparison
    mas_records: list[TickRecord]
    baseline_records: list[TickRecord]
    mas_sim: Simulation | None = None  # живая симуляция есть только сразу после запуска
    baseline_sim: BaselineSimulation | None = None

    @classmethod
    def from_live(
        cls, comparison: Comparison, mas: Simulation, baseline: BaselineSimulation
    ) -> "RunView":
        return cls(
            comparison.scenario, comparison.seed, comparison.days, comparison,
            mas.records, baseline.records, mas, baseline,
        )

    @classmethod
    def from_saved(cls, directory, scenario: str, seed: int, days: int) -> "RunView":
        runs = {}
        for mode in MODES:
            path = Path(directory) / run_filename(scenario, mode, seed, days)
            if not path.is_file():
                raise ValueError(
                    f"Нет сохранённого прогона «{mode}» для {scenario}, seed {seed}, {days} сут."
                )
            runs[mode] = load_run(path)
        comparison = Comparison(
            scenario=scenario, seed=seed, days=days,
            baseline=runs["baseline"].summary, mas=runs["mas"].summary,
        )
        return cls(
            scenario, seed, days, comparison,
            runs["mas"].records, runs["baseline"].records,
        )
"""Прогон базового и мультиагентного сценариев с отчётом о ходе выполнения."""

from collections.abc import Callable

from mas.baseline import BaselineSimulation
from mas.comparison import Comparison
from mas.engine import DEFAULT_WARMUP_DAYS, Simulation
from mas.ev_generator import generate_profiles
from mas.metrics import summarize
from mas.scenario import ScenarioConfig

ProgressCallback = Callable[[float, str], None]


def run_pair(
    config: ScenarioConfig,
    models,
    warmup_days: int = DEFAULT_WARMUP_DAYS,
    progress: ProgressCallback | None = None,
) -> tuple[Comparison, Simulation, BaselineSimulation]:
    """Те же два прогона, что в run_comparison, но с вызовом progress(доля, подпись) после такта."""
    profiles = generate_profiles(config, models)
    baseline = BaselineSimulation(config, profiles)
    mas = Simulation(config, profiles, warmup_days=warmup_days)
    total = baseline.total_ticks + mas.total_ticks
    done = 0
    for label, sim in (("Базовый сценарий", baseline), ("Мультиагентная система", mas)):
        while not sim.finished:
            sim.step()
            done += 1
            if progress:
                progress(done / total, label)
        sim.finalize()
    comparison = Comparison(
        scenario=config.name, seed=config.seed, days=config.days,
        baseline=summarize(baseline), mas=summarize(mas),
    )
    return comparison, mas, baseline
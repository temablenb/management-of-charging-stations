"""Сравнение мультиагентной системы с базовым сценарием на одних и тех же автомобилях."""
from dataclasses import dataclass

from mas.baseline import BaselineSimulation
from mas.engine import DEFAULT_WARMUP_DAYS, Simulation
from mas.ev_generator import generate_profiles
from mas.metrics import RunSummary, summarize
from mas.scenario import ScenarioConfig

EPSILON = 1e-9


@dataclass(frozen=True)
class MetricSpec:
    """Описание показателя: поле итогов, подпись, единица и что считать улучшением."""

    key: str
    label: str
    unit: str
    lower_is_better: bool | None  # None: показатель нейтральный
    decimals: int = 0


METRICS = (
    MetricSpec("overload_ticks", "Тактов с превышением лимита", "тактов", True),
    MetricSpec("overload_kwh", "Энергия сверх лимита", "кВт·ч", True, 1),
    MetricSpec("max_overload_kw", "Максимальное превышение лимита", "кВт", True, 1),
    MetricSpec("peak_load_kw", "Пиковая нагрузка на подстанцию", "кВт", True, 1),
    MetricSpec("operator_cost_rub", "Затраты оператора", "руб", True),
    MetricSpec("purchase_cost_rub", "  из них закупка энергии", "руб", True),
    MetricSpec("overload_penalty_rub", "  из них штраф за превышение", "руб", True),
    MetricSpec("avg_price_rub_per_kwh", "Средняя цена для водителей", "руб/кВт·ч", True, 2),
    MetricSpec("revenue_rub", "Выручка от водителей", "руб", None),
    MetricSpec("margin_rub", "Маржа оператора (выручка минус затраты)", "руб", False),
    MetricSpec("energy_kwh", "Выдано энергии", "кВт·ч", False, 1),
    MetricSpec("deadline_met_share", "Доля успевших к дедлайну", "%", False, 1),
    MetricSpec("missed", "Опоздавших автомобилей", "шт.", True),
    MetricSpec("avg_wait_ticks", "Среднее ожидание в очереди", "тактов", True, 2),
    MetricSpec("max_wait_ticks", "Максимальное ожидание в очереди", "тактов", True),
)

BETTER = "better"
WORSE = "worse"
EQUAL = "equal"
NEUTRAL = "neutral"


@dataclass(frozen=True)
class ComparisonRow:
    """Один показатель в двух прогонах и его изменение."""

    spec: MetricSpec
    baseline: float
    mas: float

    @property
    def delta(self) -> float:
        return self.mas - self.baseline

    @property
    def delta_pct(self) -> float | None:
        """Изменение в процентах от базового значения (None, если оно нулевое)."""
        if abs(self.baseline) < EPSILON:
            return None
        return self.delta / abs(self.baseline) * 100.0

    @property
    def verdict(self) -> str:
        """Лучше, хуже или без изменений для мультиагентной системы."""
        if self.spec.lower_is_better is None:
            return NEUTRAL
        if abs(self.delta) < EPSILON:
            return EQUAL
        improved = self.delta < 0 if self.spec.lower_is_better else self.delta > 0
        return BETTER if improved else WORSE


@dataclass(frozen=True)
class Comparison:
    """Итоги двух прогонов одного сценария."""

    scenario: str
    seed: int
    days: int
    baseline: RunSummary
    mas: RunSummary

    def rows(self) -> list[ComparisonRow]:
        return [
            ComparisonRow(spec, float(getattr(self.baseline, spec.key)),
                          float(getattr(self.mas, spec.key)))
            for spec in METRICS
        ]

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "seed": self.seed,
            "days": self.days,
            "baseline": self.baseline.to_dict(),
            "mas": self.mas.to_dict(),
            "rows": [
                {
                    "key": row.spec.key,
                    "label": row.spec.label.strip(),
                    "unit": row.spec.unit,
                    "baseline": row.baseline,
                    "mas": row.mas,
                    "delta": row.delta,
                    "delta_pct": row.delta_pct,
                    "verdict": row.verdict,
                }
                for row in self.rows()
            ],
        }


def run_comparison(
    config: ScenarioConfig,
    models,
    warmup_days: int = DEFAULT_WARMUP_DAYS,
) -> tuple[Comparison, Simulation, BaselineSimulation]:
    """Прогоняет базовый и мультиагентный сценарии на одном потоке автомобилей."""
    profiles = generate_profiles(config, models)
    baseline = BaselineSimulation(config, profiles)
    baseline.run()
    mas = Simulation(config, profiles, warmup_days=warmup_days)
    mas.run()
    comparison = Comparison(
        scenario=config.name, seed=config.seed, days=config.days,
        baseline=summarize(baseline), mas=summarize(mas),
    )
    return comparison, mas, baseline


def format_value(spec: MetricSpec, value: float) -> str:
    """Значение показателя для таблицы (доля показывается в процентах)."""
    if spec.unit == "%":
        value *= 100.0
    return f"{value:.{spec.decimals}f}"


def format_delta(row: ComparisonRow) -> str:
    """Изменение показателя в мультиагентной системе: процент или разность и пометка."""
    marks = {BETTER: "лучше", WORSE: "хуже", EQUAL: "без изменений", NEUTRAL: ""}
    if abs(row.delta) < EPSILON:
        change = "0"
    elif row.delta_pct is None:
        change = f"{row.delta:+.{row.spec.decimals}f}"
    else:
        change = f"{row.delta_pct:+.1f}%"
    return f"{change} {marks[row.verdict]}".strip()


def format_comparison(comparison: Comparison) -> str:
    """Таблица сравнения для консоли."""
    rows = comparison.rows()
    label_width = max(len(row.spec.label) for row in rows)
    unit_width = max(len(row.spec.unit) for row in rows)
    lines = [
        f"Сравнение: {comparison.scenario} ({comparison.days} сут., seed {comparison.seed})",
        f"{'Показатель':<{label_width}}  {'Ед.':<{unit_width}}  "
        f"{'Базовый':>10}  {'MAS':>10}  Изменение MAS",
    ]
    for row in rows:
        lines.append(
            f"{row.spec.label:<{label_width}}  {row.spec.unit:<{unit_width}}  "
            f"{format_value(row.spec, row.baseline):>10}  "
            f"{format_value(row.spec, row.mas):>10}  {format_delta(row)}"
        )
    return "\n".join(lines)
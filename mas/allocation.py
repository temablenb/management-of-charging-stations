"""Распределение ограниченной мощности подстанции между станциями.

Задача линейного программирования: максимизировать суммарную
(взвешенную) выделенную мощность при ограничениях:
  - сумма выделенной мощности не больше лимита подстанции;
  - станция получает не больше, чем запросила и чем позволяет её мощность;
  - станция получает не меньше доли MIN_SHARE от своей потребности.
Мощность в кВт.
"""
from dataclasses import dataclass

import pulp

MIN_SHARE = 0.6
EPS = 1e-9


class AllocationInfeasible(Exception):
    """Гарантированные минимумы станций не помещаются в лимит подстанции."""


@dataclass(frozen=True)
class AllocationResult:
    """Результат распределения: мощность по станциям и признак дефицита."""

    allocated_kw: dict[str, float]
    deficit: bool

    @property
    def total_kw(self) -> float:
        return sum(self.allocated_kw.values())


def _validate(demands, max_powers, limit_kw, min_share, weights) -> None:
    if limit_kw < 0:
        raise ValueError("Лимит подстанции не может быть отрицательным")
    if set(demands) != set(max_powers):
        raise ValueError("Наборы станций в потребностях и мощностях не совпадают")
    if any(value < 0 for value in demands.values()):
        raise ValueError("Потребность станции не может быть отрицательной")
    if any(value <= 0 for value in max_powers.values()):
        raise ValueError("Мощность станции должна быть положительной")
    if not 0.0 <= min_share <= 1.0:
        raise ValueError("Гарантированная доля должна быть от 0 до 1")
    if weights is not None:
        if set(weights) != set(demands):
            raise ValueError("Набор станций в весах не совпадает с потребностями")
        if any(value <= 0 for value in weights.values()):
            raise ValueError("Веса станций должны быть положительными")


def _solve_lp(caps, limit_kw, min_share, weights) -> dict[str, float]:
    floors = {s: min_share * cap for s, cap in caps.items()}
    if sum(floors.values()) > limit_kw + EPS:
        raise AllocationInfeasible(
            f"Гарантированный минимум {sum(floors.values()):.1f} кВт "
            f"превышает лимит {limit_kw:.1f} кВт"
        )

    problem = pulp.LpProblem("PowerAllocation", pulp.LpMaximize)
    power = {
        station: pulp.LpVariable(f"P_{index}", lowBound=floors[station], upBound=caps[station])
        for index, station in enumerate(caps)
    }
    weight = weights or {station: 1.0 for station in caps}
    problem += pulp.lpSum(weight[station] * power[station] for station in caps)
    problem += pulp.lpSum(power.values()) <= limit_kw, "SubstationLimit"
    problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=10))

    status = pulp.LpStatus[problem.status]
    if status != "Optimal":
        raise AllocationInfeasible(f"Решатель вернул статус {status}")

    return {
        station: round(min(max(power[station].value() or 0.0, floors[station]), caps[station]), 6)
        for station in caps
    }


def allocate_power(
    demands: dict[str, float],
    max_powers: dict[str, float],
    limit_kw: float,
    min_share: float = MIN_SHARE,
    weights: dict[str, float] | None = None,
) -> AllocationResult:
    _validate(demands, max_powers, limit_kw, min_share, weights)
    caps = {s: min(demands[s], max_powers[s]) for s in demands}
    if sum(caps.values()) <= limit_kw + EPS:
        return AllocationResult(dict(caps), deficit=False)
    allocated = _solve_lp(caps, limit_kw, min_share, weights)
    return AllocationResult(allocated, deficit=True)
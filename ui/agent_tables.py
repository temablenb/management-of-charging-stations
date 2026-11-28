"""Таблицы по агентам для страницы «Симуляция»."""

from statistics import mean

import pandas as pd

DECISION_COLUMNS = ["tick", "requested_kw", "allocated_kw", "avg_multiplier"]
VEHICLE_COLUMNS = ["ev", "state", "delivered_kwh", "cost_rub", "finish_tick"]


def _text(value) -> str:
    return str(getattr(value, "value", value))


def decisions_frame(sim) -> pd.DataFrame:
    """Решения Grid Agent по тактам: запрошено, выделено, средний тарифный множитель."""
    rows = [
        {
            "tick": decision.tick,
            "requested_kw": decision.requested_kw,
            "allocated_kw": decision.allocated_kw,
            "avg_multiplier": mean(decision.multipliers.values()) if decision.multipliers else 1.0,
        }
        for decision in sim.grid.decisions
    ]
    return pd.DataFrame(rows, columns=DECISION_COLUMNS)


def vehicles_frame(sim) -> pd.DataFrame:
    """Итоговое состояние каждого автомобиля."""
    rows = [
        {
            "ev": ev.agent_id,
            "state": _text(ev.state),
            "delivered_kwh": ev.delivered_kwh,
            "cost_rub": ev.cost_rub,
            "finish_tick": ev.finish_tick,
        }
        for ev in sim.evs
    ]
    return pd.DataFrame(rows, columns=VEHICLE_COLUMNS)
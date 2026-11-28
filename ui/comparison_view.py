"""Таблица сравнения мультиагентной системы с базовым сценарием."""

import pandas as pd

from mas.comparison import (
    BETTER, EQUAL, NEUTRAL, WORSE, Comparison, format_delta, format_value,
)

VERDICT_LABELS = {BETTER: "лучше", WORSE: "хуже", EQUAL: "без изменений", NEUTRAL: "—"}
VERDICT_COLORS = {
    "лучше": "background-color: rgba(40,167,69,0.25)",
    "хуже": "background-color: rgba(220,53,69,0.25)",
}


def comparison_frame(comparison: Comparison) -> pd.DataFrame:
    rows = [
        {
            "Показатель": row.spec.label.strip(),
            "Базовый": format_value(row.spec, row.baseline),
            "Мультиагентная": format_value(row.spec, row.mas),
            "Изменение": format_delta(row),
            "Итог": VERDICT_LABELS[row.verdict],
        }
        for row in comparison.rows()
    ]
    return pd.DataFrame(rows)


def styled_comparison(comparison: Comparison):
    """Таблица с подсветкой столбца «Итог» для st.dataframe."""
    frame = comparison_frame(comparison)
    return frame.style.map(lambda value: VERDICT_COLORS.get(value, ""), subset=["Итог"])
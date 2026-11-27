"""Показ результатов прогона."""

import streamlit as st

from mas.comparison import Comparison, format_value
from ui.run_view import RunView

HEADLINE_KEYS = ("overload_ticks", "operator_cost_rub", "peak_load_kw", "deadline_met_share")


def _delta_color(spec) -> str:
    if spec.lower_is_better is None:
        return "off"
    return "inverse" if spec.lower_is_better else "normal"


def show_headline(comparison: Comparison) -> None:
    """Четыре главных показателя мультиагентной системы с отличием от базового."""
    rows = {row.spec.key: row for row in comparison.rows()}
    for column, key in zip(st.columns(len(HEADLINE_KEYS)), HEADLINE_KEYS):
        row = rows[key]
        spec = row.spec
        column.metric(
            spec.label,
            format_value(spec, row.mas),
            f"{row.delta:+.{spec.decimals}f} {spec.unit}",
            delta_color=_delta_color(spec),
            help=f"Базовый сценарий: {format_value(spec, row.baseline)}",
        )


def render_results(view: RunView) -> None:
    st.divider()
    st.subheader(f"Результаты: {view.scenario} · seed {view.seed} · {view.days} сут.")
    show_headline(view.comparison)
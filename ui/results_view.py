"""Показ результатов прогона."""

import streamlit as st

from mas.comparison import Comparison, format_value
from ui.run_view import RunView
from ui.charts import (
    price_figure, slice_days, soc_figure, station_load_figure, total_load_figure,
)

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
    (tab_charts,) = st.tabs(["Графики"])
    with tab_charts:
        render_charts(view)


def render_charts(view: RunView) -> None:
    mas_records, baseline_records = view.mas_records, view.baseline_records
    if view.days > 1:
        first, last = st.slider(
            "Сутки", 1, view.days, (1, view.days), key=f"sim_days_range_{view.days}"
        )
        mas_records = slice_days(mas_records, first, last)
        baseline_records = slice_days(baseline_records, first, last)
    st.plotly_chart(
        station_load_figure(mas_records, "Нагрузка по станциям (мультиагентная система)"),
        use_container_width=True,
    )
    st.plotly_chart(total_load_figure(mas_records, baseline_records), use_container_width=True)
    st.plotly_chart(price_figure(mas_records, baseline_records), use_container_width=True)
    soc = soc_figure(mas_records)
    if soc is None:
        st.info("В этом сценарии нет накопителя энергии.")
    else:
        st.plotly_chart(soc, use_container_width=True)
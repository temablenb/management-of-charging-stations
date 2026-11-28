"""Показ результатов прогона."""

import streamlit as st
import pandas as pd

from ui.agent_tables import decisions_frame, vehicles_frame
from ui.charts import queue_figure
from ui.comparison_view import styled_comparison
from ui.journal_view import filter_journal, journal_frame
from mas.comparison import Comparison, format_value
from ui.run_view import RunView
from ui.charts import (
    price_figure, slice_days, soc_figure, station_load_figure, total_load_figure,
)

MAX_JOURNAL_ROWS = 1000
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
    st.dataframe(styled_comparison(view.comparison), hide_index=True, use_container_width=True)
    tab_charts, tab_queues, tab_journal = st.tabs(
        ["Графики", "Очереди и решения", "Журнал агентов"]
    )
    with tab_charts:
        render_charts(view)
    with tab_queues:
        render_queues(view)
    with tab_journal:
        render_journal(view)


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


def render_queues(view: RunView) -> None:
    station_ids = list(view.mas_records[0].station_kw) if view.mas_records else []
    if not station_ids:
        st.info("Нет данных по станциям.")
        return
    station_id = st.selectbox("Станция", station_ids, key="sim_queue_station")
    st.plotly_chart(queue_figure(view.mas_records, station_id), use_container_width=True)
    if view.mas_sim is None:
        st.caption("Решения Grid Agent и состояние автомобилей доступны только сразу после запуска.")
        return
    st.markdown("**Решения Grid Agent**")
    decisions = decisions_frame(view.mas_sim).rename(columns={
        "tick": "Такт", "requested_kw": "Запрошено, кВт",
        "allocated_kw": "Выделено, кВт", "avg_multiplier": "Средний множитель",
    })
    st.dataframe(decisions, hide_index=True, use_container_width=True)
    st.markdown("**Автомобили**")
    vehicles = vehicles_frame(view.mas_sim).rename(columns={
        "ev": "Автомобиль", "state": "Состояние", "delivered_kwh": "Заряжено, кВт·ч",
        "cost_rub": "Стоимость, руб", "finish_tick": "Такт окончания",
    })
    st.dataframe(vehicles, hide_index=True, use_container_width=True)


def render_journal(view: RunView) -> None:
    if view.mas_sim is None:
        st.info("Журнал сообщений не сохраняется в файл. Запусти сценарий заново, чтобы увидеть его.")
        return
    frame = journal_frame(view.mas_sim)
    if frame.empty:
        st.info("Журнал пуст.")
        return
    col1, col2, col3 = st.columns(3)
    types = col1.multiselect("Тип сообщения", sorted(frame["type"].unique()), key="sim_journal_types")
    sender = col2.selectbox("Отправитель", [""] + sorted(frame["sender"].unique()), key="sim_journal_sender")
    receiver = col3.selectbox("Получатель", [""] + sorted(frame["receiver"].unique()), key="sim_journal_receiver")
    last_tick = int(frame["tick"].max())
    tick_range = (0, last_tick)
    if last_tick > 0:
        tick_range = st.slider("Такты", 0, last_tick, (0, last_tick), key="sim_journal_ticks")
    filtered = filter_journal(frame, types, sender, receiver, tick_range)
    st.caption(f"Сообщений: {len(filtered)} из {len(frame)}. Показаны первые {MAX_JOURNAL_ROWS}.")
    st.dataframe(
        filtered.head(MAX_JOURNAL_ROWS).rename(columns={
            "tick": "Такт", "type": "Тип", "sender": "Отправитель", "receiver": "Получатель",
        }),
        hide_index=True, use_container_width=True,
    )
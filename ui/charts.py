"""Графики Plotly для результатов симуляции."""

import plotly.graph_objects as go

from mas.clock import TICKS_PER_DAY
from mas.metrics import TickRecord

HOURS_PER_DAY = 24
X_TITLE = "Время, ч от начала"


def tick_hours(tick: int) -> float:
    """Время от начала симуляции в часах."""
    return tick * HOURS_PER_DAY / TICKS_PER_DAY


def _hours(records: list[TickRecord]) -> list[float]:
    return [tick_hours(record.tick) for record in records]


def _limit_line(figure: go.Figure, records: list[TickRecord]) -> None:
    if records:
        figure.add_hline(
            y=records[0].limit_kw, line_dash="dash", line_color="red",
            annotation_text="Лимит подстанции",
        )


def station_load_figure(records: list[TickRecord], title: str = "Нагрузка по станциям") -> go.Figure:
    """Мощность зарядки каждой станции и лимит подстанции."""
    figure = go.Figure()
    if records:
        x = _hours(records)
        for station_id in records[0].station_kw:
            figure.add_trace(go.Scatter(
                x=x, y=[record.station_kw[station_id] for record in records],
                name=station_id, mode="lines",
            ))
    _limit_line(figure, records)
    figure.update_layout(
        title=title, xaxis_title=X_TITLE, yaxis_title="Мощность, кВт",
        height=380, legend=dict(orientation="h"),
    )
    return figure


def total_load_figure(
    mas_records: list[TickRecord],
    baseline_records: list[TickRecord],
    title: str = "Суммарная нагрузка на подстанцию",
) -> go.Figure:
    """Нагрузка на подстанцию в двух сценариях относительно лимита."""
    figure = go.Figure()
    for name, records, color in (
        ("Мультиагентная система", mas_records, "#2a9d8f"),
        ("Базовый сценарий", baseline_records, "#e76f51"),
    ):
        figure.add_trace(go.Scatter(
            x=_hours(records), y=[record.grid_kw for record in records],
            name=name, mode="lines", line=dict(color=color),
        ))
    _limit_line(figure, mas_records)
    figure.update_layout(
        title=title, xaxis_title=X_TITLE, yaxis_title="Мощность, кВт",
        height=380, legend=dict(orientation="h"),
    )
    return figure
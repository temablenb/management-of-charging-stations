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


def mean_price(record: TickRecord) -> float:
    return sum(record.price.values()) / len(record.price) if record.price else 0.0


def price_figure(
        mas_records: list[TickRecord],
        baseline_records: list[TickRecord],
        title: str = "Тариф по времени",
) -> go.Figure:
    """Цена по станциям в мультиагентной системе и средняя плоская цена базового сценария."""
    figure = go.Figure()
    if mas_records:
        x = _hours(mas_records)
        for station_id in mas_records[0].price:
            figure.add_trace(go.Scatter(
                x=x, y=[record.price[station_id] for record in mas_records],
                name=station_id, mode="lines", line=dict(width=1), opacity=0.6,
            ))
    figure.add_trace(go.Scatter(
        x=_hours(baseline_records), y=[mean_price(record) for record in baseline_records],
        name="Базовый (плоский тариф)", mode="lines", line=dict(color="black", dash="dash"),
    ))
    figure.update_layout(
        title=title, xaxis_title=X_TITLE, yaxis_title="руб/кВт·ч",
        height=380, legend=dict(orientation="h"),
    )
    return figure


def soc_figure(records: list[TickRecord], title: str = "Накопитель энергии") -> go.Figure | None:
    """Уровень заряда накопителя и мощность заряда и отдачи; None, если накопителя нет."""
    if not records or records[0].storage_soc is None:
        return None
    x = _hours(records)
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=x, y=[record.storage_soc * 100 for record in records],
        name="SoC, %", mode="lines", line=dict(color="#264653"),
    ))
    figure.add_trace(go.Bar(
        x=x, y=[record.storage_charge_kw for record in records],
        name="Заряд, кВт", yaxis="y2", marker_color="#2a9d8f", opacity=0.5,
    ))
    figure.add_trace(go.Bar(
        x=x, y=[-record.storage_discharge_kw for record in records],
        name="Отдача, кВт", yaxis="y2", marker_color="#e76f51", opacity=0.5,
    ))
    figure.update_layout(
        title=title, xaxis_title=X_TITLE, barmode="relative", height=380,
        yaxis=dict(title="SoC, %", range=[0, 100]),
        yaxis2=dict(title="Мощность, кВт", overlaying="y", side="right"),
        legend=dict(orientation="h"),
    )
    return figure


def slice_days(records: list[TickRecord], first_day: int, last_day: int) -> list[TickRecord]:
    """Записи за сутки с first_day по last_day включительно (нумерация с 1)."""
    if first_day < 1 or last_day < first_day:
        raise ValueError("Сутки заданы неверно")
    start = (first_day - 1) * TICKS_PER_DAY
    stop = last_day * TICKS_PER_DAY
    return [record for record in records if start <= record.tick < stop]


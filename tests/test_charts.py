import pytest

from mas.clock import TICKS_PER_DAY
from mas.metrics import TickRecord
from ui.charts import (
    price_figure, soc_figure, station_load_figure, tick_hours, total_load_figure, slice_days, queue_figure
)


def make_records(count=TICKS_PER_DAY * 2, soc=None):
    return [
        TickRecord(
            tick=tick,
            station_kw={"st-1": 10.0 + tick, "st-2": 20.0},
            charging={"st-1": 1, "st-2": 2},
            waiting={"st-1": 0, "st-2": 3},
            price={"st-1": 10.0, "st-2": 14.0},
            storage_charge_kw=5.0 if soc is not None and tick % 2 == 0 else 0.0,
            storage_discharge_kw=3.0 if soc is not None and tick % 2 == 1 else 0.0,
            storage_soc=soc,
            limit_kw=100.0,
        )
        for tick in range(count)
    ]


def test_tick_hours_converts_ticks_to_hours():
    assert tick_hours(0) == 0.0
    assert tick_hours(TICKS_PER_DAY // 2) == 12.0
    assert tick_hours(TICKS_PER_DAY) == 24.0


def test_station_load_has_trace_per_station_and_limit_line():
    figure = station_load_figure(make_records())
    assert len(figure.data) == 2
    assert len(figure.layout.shapes) == 1


def test_station_load_of_empty_records_is_empty():
    assert len(station_load_figure([]).data) == 0


def test_total_load_compares_two_runs():
    records = make_records()
    figure = total_load_figure(records, records)
    assert [trace.name for trace in figure.data] == ["Мультиагентная система", "Базовый сценарий"]
    assert list(figure.data[0].y) == [record.grid_kw for record in records]


def test_price_has_station_traces_and_flat_baseline():
    records = make_records()
    figure = price_figure(records, records)
    assert len(figure.data) == 3
    assert figure.data[-1].y[0] == pytest.approx(12.0)


def test_soc_figure_is_none_without_storage():
    assert soc_figure(make_records()) is None


def test_soc_figure_has_level_and_power_traces():
    figure = soc_figure(make_records(soc=0.5))
    assert len(figure.data) == 3
    assert figure.data[0].y[0] == pytest.approx(50.0)


def test_slice_days_keeps_requested_days():
    part = slice_days(make_records(), 2, 2)
    assert len(part) == TICKS_PER_DAY
    assert part[0].tick == TICKS_PER_DAY


def test_slice_days_rejects_wrong_range():
    with pytest.raises(ValueError):
        slice_days(make_records(), 2, 1)
    with pytest.raises(ValueError):
        slice_days(make_records(), 0, 1)


def test_queue_figure_stacks_charging_and_waiting():
    figure = queue_figure(make_records(), "st-2")
    assert [trace.name for trace in figure.data] == ["Заряжаются", "Ожидают"]
    assert figure.data[1].y[0] == 3


def test_queue_figure_of_unknown_station_is_zero():
    figure = queue_figure(make_records(), "st-99")
    assert set(figure.data[0].y) == {0}
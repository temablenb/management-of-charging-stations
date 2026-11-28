import pytest

from mas.cli import DEFAULT_MODELS_PATH, apply_overrides, run_scenario
from mas.ev_models import load_ev_models
from ui.journal_view import COLUMNS, filter_journal, journal_frame
from ui.scenarios import load_by_name

CONFIG = apply_overrides(load_by_name("default"), days=1, ev_per_day=15)


@pytest.fixture(scope="module")
def sim():
    simulation, _ = run_scenario(CONFIG, load_ev_models(DEFAULT_MODELS_PATH), warmup_days=1)
    return simulation


@pytest.fixture(scope="module")
def frame(sim):
    return journal_frame(sim)


def test_frame_has_row_per_entry(sim, frame):
    assert len(frame) == len(sim.bus.journal) > 0
    assert list(frame.columns) == COLUMNS


def test_empty_filters_return_everything(frame):
    assert len(filter_journal(frame)) == len(frame)


def test_filter_by_type(frame):
    kind = frame["type"].iloc[0]
    result = filter_journal(frame, types=[kind])
    assert len(result) > 0 and set(result["type"]) == {kind}


def test_filter_by_sender_and_receiver(frame):
    first = frame.iloc[0]
    result = filter_journal(frame, sender=first["sender"], receiver=first["receiver"])
    assert len(result) > 0
    assert set(result["sender"]) == {first["sender"]}
    assert set(result["receiver"]) == {first["receiver"]}


def test_filter_by_tick_range(frame):
    result = filter_journal(frame, tick_range=(10, 20))
    assert len(result) > 0
    assert result["tick"].between(10, 20).all()
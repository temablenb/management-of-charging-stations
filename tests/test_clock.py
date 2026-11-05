import pytest

from mas.clock import SimulationClock, TICKS_PER_DAY, format_tick, hour_of_tick


def test_clock_starts_at_zero():
    clock = SimulationClock()
    assert clock.tick == 0
    assert clock.time_str == "00:00"


def test_clock_rejects_negative_start():
    with pytest.raises(ValueError):
        SimulationClock(start_tick=-1)


def test_advance_moves_tick():
    clock = SimulationClock()
    assert clock.advance() == 1
    assert clock.advance(4) == 5


def test_advance_rejects_non_positive_steps():
    with pytest.raises(ValueError):
        SimulationClock().advance(0)


def test_time_after_five_ticks():
    clock = SimulationClock(start_tick=5)
    assert clock.hour == 1
    assert clock.time_str == "01:15"


def test_last_tick_of_day():
    clock = SimulationClock(start_tick=TICKS_PER_DAY - 1)
    assert clock.day == 0
    assert clock.time_str == "23:45"


def test_day_rollover():
    clock = SimulationClock(start_tick=TICKS_PER_DAY)
    assert clock.day == 1
    assert clock.time_str == "00:00"


def test_reset_returns_to_start():
    clock = SimulationClock(start_tick=200)
    clock.reset()
    assert clock.tick == 0
    assert clock.day == 0


def test_hour_of_tick_and_format_tick():
    assert hour_of_tick(34) == 8
    assert format_tick(34) == "08:30"
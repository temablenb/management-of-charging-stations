"""Часы симуляции: перевод номера такта во время суток."""

TICK_MINUTES = 15
TICKS_PER_HOUR = 60 // TICK_MINUTES
TICKS_PER_DAY = 24 * TICKS_PER_HOUR


def tick_of_day(tick: int) -> int:
    return tick % TICKS_PER_DAY


def hour_of_tick(tick: int) -> int:
    return tick_of_day(tick) // TICKS_PER_HOUR


def format_tick(tick: int) -> str:
    minutes = (tick_of_day(tick) % TICKS_PER_HOUR) * TICK_MINUTES
    return f"{hour_of_tick(tick):02d}:{minutes:02d}"


class SimulationClock:
    def __init__(self, start_tick: int = 0) -> None:
        if start_tick < 0:
            raise ValueError("Номер такта не может быть отрицательным")
        self._tick = start_tick

    @property
    def tick(self) -> int:
        return self._tick

    @property
    def day(self) -> int:
        return self._tick // TICKS_PER_DAY

    @property
    def hour(self) -> int:
        return hour_of_tick(self._tick)

    @property
    def time_str(self) -> str:
        return format_tick(self._tick)

    def advance(self, steps: int = 1) -> int:
        if steps < 1:
            raise ValueError("Шаг времени должен быть не меньше одного такта")
        self._tick += steps
        return self._tick

    def reset(self) -> None:
        self._tick = 0
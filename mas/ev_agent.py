"""Electric Vehicle Agent: автомобиль подаёт заявку станции и ждёт плана зарядки."""
from dataclasses import dataclass
from enum import Enum

import numpy as np


class EVState(str, Enum):
    PENDING = "pending"          # ещё не подал заявку
    REQUESTED = "requested"      # заявка отправлена, плана пока нет
    QUEUED = "queued"            # ждёт места на станции
    CHARGING = "charging"        # заряжается
    DONE = "done"                # зарядка завершена
    MISSED = "missed"            # дедлайн прошёл, зарядка не завершена
    NO_STATION = "no_station"    # нет станции с подходящим разъёмом


@dataclass(frozen=True)
class EVProfile:
    """Параметры автомобиля и его потребности."""

    ev_id: str
    battery_kwh: float
    soc: float
    target_soc: float
    max_charge_kw: float
    connector: str
    arrival_tick: int
    deadline_tick: int
    prepaid: bool = False

    def __post_init__(self):
        if self.battery_kwh <= 0:
            raise ValueError("Ёмкость батареи должна быть положительной")
        if not 0.0 <= self.soc < self.target_soc <= 1.0:
            raise ValueError("Должно выполняться 0 <= начальный заряд < целевой <= 1")
        if self.max_charge_kw <= 0:
            raise ValueError("Максимальная мощность зарядки должна быть положительной")
        if self.arrival_tick < 0:
            raise ValueError("Такт приезда не может быть отрицательным")
        if self.deadline_tick <= self.arrival_tick:
            raise ValueError("Дедлайн должен быть позже такта приезда")

    @property
    def needed_kwh(self) -> float:
        """Сколько энергии нужно, чтобы довести заряд до целевого."""
        return self.battery_kwh * (self.target_soc - self.soc)


@dataclass(frozen=True)
class StationInfo:
    """Что автомобиль знает о станции заранее: разъём и мощность."""

    station_id: str
    connector: str
    max_power_kw: float


def choose_station(
    stations, connector: str, rng: np.random.Generator
) -> StationInfo | None:
    """Случайная (по seed) станция с подходящим разъёмом; None, если таких нет."""
    compatible = sorted(
        (station for station in stations if station.connector == connector),
        key=lambda station: station.station_id,
    )
    if not compatible:
        return None
    return compatible[int(rng.integers(len(compatible)))]
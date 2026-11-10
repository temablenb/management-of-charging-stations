"""Electric Vehicle Agent: автомобиль подаёт заявку станции и ждёт плана зарядки."""
from dataclasses import dataclass
from enum import Enum

import numpy as np

from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.messages import ChargePlan, ChargeRequest, Message

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


class EVAgent(BaseAgent):
    def __init__(
        self,
        bus: MessageBus,
        profile: EVProfile,
        stations,
        rng: np.random.Generator,
    ) -> None:
        super().__init__(profile.ev_id, bus)
        self.profile = profile
        self.stations = tuple(stations)
        self.rng = rng
        self.state = EVState.PENDING
        self.current_tick = 0
        self.station_id: str | None = None
        self.request_tick: int | None = None
        self.queue_position: int | None = None
        self.expected_finish_tick: int | None = None
        self.soc = profile.soc
        self.delivered_kwh = 0.0
        self.cost_rub = 0.0
        self.finish_tick: int | None = None

    @property
    def finished(self) -> bool:
        return self.state in (EVState.DONE, EVState.MISSED, EVState.NO_STATION)

    @property
    def deadline_met(self) -> bool:
        return (
            self.state == EVState.DONE
            and self.finish_tick is not None
            and self.finish_tick <= self.profile.deadline_tick
        )

    def begin_tick(self, tick: int) -> None:
        self.current_tick = tick
        if self.finished:
            return
        if self.state == EVState.PENDING:
            if tick >= self.profile.deadline_tick:
                self.state = EVState.MISSED  # приехал слишком поздно, подавать заявку нет смысла
            elif tick >= self.profile.arrival_tick:
                self._send_request(tick)
        elif tick > self.profile.deadline_tick:
            self.state = EVState.MISSED

    def _send_request(self, tick: int) -> None:
        station = choose_station(self.stations, self.profile.connector, self.rng)
        if station is None:
            self.state = EVState.NO_STATION
            return
        self.station_id = station.station_id
        self.request_tick = tick
        self.send(ChargeRequest(
            sender=self.agent_id,
            receiver=station.station_id,
            tick=tick,
            energy_kwh=self.profile.needed_kwh,
            deadline_tick=self.profile.deadline_tick,
            max_power_kw=self.profile.max_charge_kw,
            connector=self.profile.connector,
            prepaid=self.profile.prepaid,
        ))
        self.state = EVState.REQUESTED

    def handle(self, message: Message) -> None:
        if isinstance(message, ChargePlan):
            self._apply_plan(message)
        else:
            super().handle(message)

    def _apply_plan(self, plan: ChargePlan) -> None:
        if self.finished:
            return
        self.queue_position = plan.queue_position
        self.expected_finish_tick = plan.expected_finish_tick
        self.state = EVState.CHARGING if plan.queue_position == 0 else EVState.QUEUED
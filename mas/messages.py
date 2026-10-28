"""Типы сообщений, которыми обмениваются агенты.

Единицы измерения: энергия в кВт·ч, мощность в кВт,
время задаётся номером такта (1 такт = 15 минут).
"""
from dataclasses import dataclass
from enum import Enum


class MessageType(str, Enum):
    CHARGE_REQUEST = "charge_request"
    CHARGE_PLAN = "charge_plan"
    POWER_REQUEST = "power_request"
    POWER_ALLOCATION = "power_allocation"
    STORAGE_OFFER = "storage_offer"


@dataclass(frozen=True)
class Message:
    """Базовое сообщение: кто отправил, кому и в каком такте."""

    sender: str
    receiver: str
    tick: int

    @property
    def type(self) -> MessageType:
        raise NotImplementedError("Тип задаётся в наследниках")


@dataclass(frozen=True)
class ChargeRequest(Message):
    """Заявка автомобиля станции: сколько энергии нужно и к какому такту."""

    energy_kwh: float
    deadline_tick: int
    max_power_kw: float
    connector: str
    prepaid: bool

    def __post_init__(self):
        if self.energy_kwh <= 0:
            raise ValueError("Требуемая энергия должна быть положительной")
        if self.deadline_tick <= self.tick:
            raise ValueError("Дедлайн должен быть позже текущего такта")
        if self.max_power_kw <= 0:
            raise ValueError("Максимальная мощность должна быть положительной")

    @property
    def type(self) -> MessageType:
        return MessageType.CHARGE_REQUEST


@dataclass(frozen=True)
class ChargePlan(Message):
    """План станции для автомобиля: мощность по тактам и место в очереди."""

    schedule_kw: tuple[float, ...]
    expected_finish_tick: int
    queue_position: int

    @property
    def type(self) -> MessageType:
        return MessageType.CHARGE_PLAN


@dataclass(frozen=True)
class PowerRequest(Message):
    """Запрос станции к Grid Agent: потребность и прогноз нагрузки."""

    demand_kw: float
    max_power_kw: float
    forecast_kw: tuple[float, ...]

    def __post_init__(self):
        if self.demand_kw < 0:
            raise ValueError("Потребность не может быть отрицательной")
        if self.max_power_kw <= 0:
            raise ValueError("Максимальная мощность станции должна быть положительной")

    @property
    def type(self) -> MessageType:
        return MessageType.POWER_REQUEST


@dataclass(frozen=True)
class PowerAllocation(Message):
    """Ответ Grid Agent станции: выделенная мощность и тарифный множитель."""

    allocated_kw: float
    tariff_multiplier: float

    def __post_init__(self):
        if self.allocated_kw < 0:
            raise ValueError("Выделенная мощность не может быть отрицательной")
        if self.tariff_multiplier <= 0:
            raise ValueError("Тарифный множитель должен быть положительным")

    @property
    def type(self) -> MessageType:
        return MessageType.POWER_ALLOCATION


@dataclass(frozen=True)
class StorageOffer(Message):
    """Предложение накопителя Grid Agent: сколько мощности можно отдать."""

    available_kw: float
    soc: float

    def __post_init__(self):
        if self.available_kw < 0:
            raise ValueError("Доступная мощность не может быть отрицательной")
        if not 0.0 <= self.soc <= 1.0:
            raise ValueError("Уровень заряда накопителя должен быть от 0 до 1")

    @property
    def type(self) -> MessageType:
        return MessageType.STORAGE_OFFER
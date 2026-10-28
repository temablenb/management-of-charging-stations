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
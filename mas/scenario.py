"""Конфигурация сценария симуляции."""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class StationConfig:
    station_id: str
    max_power_kw: float
    connector: str
    slots: int = 5

    def __post_init__(self):
        if self.max_power_kw <= 0:
            raise ValueError("Мощность станции должна быть положительной")
        if self.slots < 1:
            raise ValueError("На станции должно быть хотя бы одно место")


@dataclass(frozen=True)
class StorageConfig:
    capacity_kwh: float
    max_power_kw: float
    efficiency: float = 0.92
    initial_soc: float = 0.5

    def __post_init__(self):
        if self.capacity_kwh <= 0:
            raise ValueError("Ёмкость накопителя должна быть положительной")
        if self.max_power_kw <= 0:
            raise ValueError("Мощность накопителя должна быть положительной")
        if not 0.0 < self.efficiency <= 1.0:
            raise ValueError("КПД накопителя должен быть в диапазоне (0; 1]")
        if not 0.0 <= self.initial_soc <= 1.0:
            raise ValueError("Начальный заряд накопителя должен быть от 0 до 1")


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    seed: int
    days: int
    substation_limit_kw: float
    base_tariff_rub: float
    tariff_min_mult: float
    tariff_max_mult: float
    ev_per_day: int
    stations: tuple[StationConfig, ...]
    storage: StorageConfig | None = None

    def __post_init__(self):
        if self.days < 1:
            raise ValueError("Сценарий должен длиться хотя бы одни сутки")
        if self.substation_limit_kw <= 0:
            raise ValueError("Лимит подстанции должен быть положительным")
        if self.base_tariff_rub <= 0:
            raise ValueError("Базовый тариф должен быть положительным")
        if not 0 < self.tariff_min_mult < self.tariff_max_mult:
            raise ValueError("Должно выполняться 0 < минимальный множитель < максимальный")
        if self.ev_per_day < 0:
            raise ValueError("Число автомобилей в сутки не может быть отрицательным")
        if not self.stations:
            raise ValueError("В сценарии должна быть хотя бы одна станция")
        ids = [station.station_id for station in self.stations]
        if len(set(ids)) != len(ids):
            raise ValueError("Идентификаторы станций должны быть уникальными")

    def rng(self) -> np.random.Generator:
        """Новый генератор случайных чисел: один seed даёт одну и ту же последовательность."""
        return np.random.default_rng(self.seed)

    @classmethod
    def from_dict(cls, data: dict) -> "ScenarioConfig":
        required = (
            "name", "seed", "days", "substation_limit_kw", "base_tariff_rub",
            "tariff_min_mult", "tariff_max_mult", "ev_per_day", "stations",
        )
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"В сценарии не заданы поля: {', '.join(missing)}")
        storage = data.get("storage")
        return cls(
            name=data["name"],
            seed=int(data["seed"]),
            days=int(data["days"]),
            substation_limit_kw=float(data["substation_limit_kw"]),
            base_tariff_rub=float(data["base_tariff_rub"]),
            tariff_min_mult=float(data["tariff_min_mult"]),
            tariff_max_mult=float(data["tariff_max_mult"]),
            ev_per_day=int(data["ev_per_day"]),
            stations=tuple(StationConfig(**item) for item in data["stations"]),
            storage=StorageConfig(**storage) if storage else None,
        )


def load_scenario(path: str | Path) -> ScenarioConfig:
    with open(path, encoding="utf-8-sig") as file:
        return ScenarioConfig.from_dict(json.load(file))
"""Каталог моделей электромобилей и создание профилей автомобилей по модели."""
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from mas.clock import TICKS_PER_HOUR
from mas.ev_agent import EVProfile
from mas.ev_behavior import SAFETY_FACTOR, min_charge_ticks

CONNECTORS = ("CCS", "CHAdeMO", "Type2", "GB/T")


@dataclass(frozen=True)
class EVModel:
    brand: str
    model: str
    battery_kwh: float
    max_charge_kw: float
    connector: str

    def __post_init__(self):
        if not self.brand or not self.model:
            raise ValueError("У модели должны быть марка и название")
        if self.battery_kwh <= 0:
            raise ValueError("Ёмкость батареи должна быть положительной")
        if self.max_charge_kw <= 0:
            raise ValueError("Максимальная мощность зарядки должна быть положительной")
        if self.connector not in CONNECTORS:
            raise ValueError(f"Неизвестный тип разъёма: {self.connector}")

    @property
    def name(self) -> str:
        return f"{self.brand} {self.model}"


def load_ev_models(path: str | Path) -> tuple[EVModel, ...]:
    """Читает каталог моделей из JSON-файла (список объектов)."""
    with open(path, encoding="utf-8-sig") as file:
        items = json.load(file)
    if not isinstance(items, list) or not items:
        raise ValueError("Каталог моделей должен быть непустым списком")
    models = []
    seen = set()
    for item in items:
        try:
            model = EVModel(
                brand=item["brand"],
                model=item["model"],
                battery_kwh=float(item["battery_kwh"]),
                max_charge_kw=float(item["max_charge_kw"]),
                connector=item["connector"],
            )
        except KeyError as error:
            raise ValueError(f"В записи модели не задано поле {error}") from error
        if model.name in seen:
            raise ValueError(f"Модель {model.name} встречается в каталоге дважды")
        seen.add(model.name)
        models.append(model)
    return tuple(models)


def make_profile(
    model: EVModel,
    ev_id: str,
    arrival_tick: int,
    rng: np.random.Generator,
    *,
    prepaid: bool = False,
    price_sensitivity: float = 0.0,
    soc_range: tuple[float, float] = (0.1, 0.5),
    target_soc: float = 0.8,
    parking_hours: tuple[float, float] = (2.0, 6.0),
) -> EVProfile:
    """Профиль автомобиля заданной модели: случайный начальный заряд и время стоянки.

    Дедлайн не раньше, чем нужно для зарядки на полной мощности автомобиля с запасом,
    поэтому заявка принципиально выполнима.
    """
    low, high = soc_range
    if not 0.0 <= low <= high < target_soc <= 1.0:
        raise ValueError("Должно выполняться 0 <= soc_min <= soc_max < целевой заряд <= 1")
    if not 0 < parking_hours[0] <= parking_hours[1]:
        raise ValueError("Время стоянки должно быть положительным и min <= max")
    soc = round(float(rng.uniform(low, high)), 3)
    parking_ticks = int(round(float(rng.uniform(*parking_hours)) * TICKS_PER_HOUR))
    needed_kwh = model.battery_kwh * (target_soc - soc)
    charge_ticks = math.ceil(min_charge_ticks(needed_kwh, model.max_charge_kw) * SAFETY_FACTOR)
    return EVProfile(
        ev_id=ev_id,
        battery_kwh=model.battery_kwh,
        soc=soc,
        target_soc=target_soc,
        max_charge_kw=model.max_charge_kw,
        connector=model.connector,
        arrival_tick=arrival_tick,
        deadline_tick=arrival_tick + max(parking_ticks, charge_ticks, 1),
        prepaid=prepaid,
        price_sensitivity=price_sensitivity,
    )
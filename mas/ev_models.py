"""Каталог моделей электромобилей и создание профилей автомобилей по модели."""
import json
from dataclasses import dataclass
from pathlib import Path

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
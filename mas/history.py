"""Предыстория нагрузки станции для прогноза в начале симуляции."""
import numpy as np

from mas.ev_generator import arrival_probabilities
from mas.scenario import ScenarioConfig, StationConfig

AVERAGE_SESSION_KWH = 30.0
NOISE_SHARE = 0.05


def warmup_history(
    config: ScenarioConfig,
    station: StationConfig,
    days: int,
    rng: np.random.Generator,
) -> list[float]:
    """Почасовая нагрузка станции за days суток до начала симуляции, кВт.

    Суточный профиль повторяет профиль приездов; суточная энергия станции равна
    доле её мощности в сети от энергии всех сессий. Ряд заканчивается часом 23:00–24:00.
    """
    if days < 1:
        raise ValueError("Предыстория должна охватывать хотя бы одни сутки")
    total_power = sum(item.max_power_kw for item in config.stations)
    daily_kwh = config.ev_per_day * AVERAGE_SESSION_KWH * station.max_power_kw / total_power
    profile = daily_kwh * arrival_probabilities()
    values = []
    for _ in range(days):
        noise = rng.normal(1.0, NOISE_SHARE, size=24)
        day = np.clip(profile * noise, 0.0, station.max_power_kw)
        values.extend(round(float(value), 3) for value in day)
    return values
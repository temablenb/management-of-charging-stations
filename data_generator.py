import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from database import init_schema, save_history, get_history, get_stations_info
from config import SIMULATION_DAYS


def generate_synthetic_data():
    if not get_history().empty:
        return

    init_schema()
    np.random.seed(42)

    now = datetime.now()
    end_date = now.replace(minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=SIMULATION_DAYS)
    dates = pd.date_range(start_date, end_date, freq="h")[:-1]
    total_records = []

    stations_df = get_stations_info()

    for _, station in stations_df.iterrows():
        sid = station['id']
        max_power = station['max_power_kw']

        for dt in dates:
            hour = dt.hour
            dow = dt.dayofweek

            base_load = max_power * 0.20
            if 7 <= hour <= 9:
                base_load += max_power * 0.28
            if 17 <= hour <= 20:
                base_load += max_power * 0.38
            if dow >= 5:
                base_load *= 0.85

            temp = 15.0 + 8 * np.sin(2 * np.pi * (hour - 14) / 24) + np.random.normal(0, 2.0)
            temp_effect = 0.4 * abs(temp - 20.0)

            event = 1 if np.random.random() < 0.01 else 0
            event_effect = event * np.random.uniform(max_power * 0.1, max_power * 0.2)

            load = max(5.0, base_load + temp_effect + event_effect + np.random.normal(0, max_power * 0.04))
            load = min(load, max_power * 0.95)

            total_records.append((sid, dt.strftime("%Y-%m-%d %H:%M:%S"), int(round(load, 2)), round(temp, 1), event))

    save_history(total_records)
    print(f"Синтетический датасет сгенерирован.")


def apply_load_adjustment(station_id: int, adjustment_factor: float, hours_ahead: int = 24):
    if adjustment_factor < 0.5 or adjustment_factor > 2.0:
        raise ValueError("Коэффициент корректировки должен быть в диапазоне 0.5 - 2.0")

    hist = get_history(station_id)
    if hist.empty:
        raise ValueError(f"Нет исторических данных для станции {station_id}")

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    future_times = [now + timedelta(hours=h) for h in range(1, hours_ahead + 1)]

    last_load = hist['load_kw'].iloc[-1]
    last_temp = hist['temperature'].iloc[-1] if 'temperature' in hist.columns else 18.0

    records = []
    for ft in future_times:
        hour = ft.hour
        hour_factor = 1.0
        if 7 <= hour <= 9:
            hour_factor = 1.4
        elif 17 <= hour <= 20:
            hour_factor = 1.6
        elif 0 <= hour <= 6 or 22 <= hour <= 23:
            hour_factor = 0.5

        base_load = last_load * hour_factor * adjustment_factor
        temp = last_temp + np.random.normal(0, 2.0)

        records.append((
            station_id,
            ft.strftime("%Y-%m-%d %H:%M:%S"),
            round(base_load, 2),
            round(temp, 1),
            0
        ))

    save_history(records)
    return len(records)
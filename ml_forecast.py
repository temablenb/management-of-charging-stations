import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from database import get_history, save_forecast
from config import FORECAST_HORIZON, HOLDOUT_HOURS


def train_and_predict_station(station_id: int) -> tuple[pd.DataFrame, float, float, dict]:
    df = get_history(station_id)
    min_required_hours = HOLDOUT_HOURS + 168
    if df.empty or len(df) < min_required_hours:
        raise ValueError(
            f"Недостаточно данных для станции {station_id}. "
            f"Имеется: {len(df)} записей, требуется минимум: {min_required_hours}."
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    ts = (df.sort_values("timestamp")
          .set_index("timestamp")["load_kw"]
          .resample("h").mean()
          .interpolate("linear"))

    if len(ts) < min_required_hours:
        raise ValueError(f"После ресемплинга недостаточно данных: {len(ts)}.")

    train = ts.iloc[:-HOLDOUT_HOURS]
    test  = ts.iloc[-HOLDOUT_HOURS:]

    hw = ExponentialSmoothing(
        train,
        trend="add",
        seasonal="add",
        seasonal_periods=24,
        initialization_method="estimated",
    ).fit(optimized=True, use_brute=False)

    test_pred = hw.forecast(HOLDOUT_HOURS)
    mae = float(np.mean(np.abs(test.values - test_pred.values)))
    sse = float(hw.sse)

    hw_full = ExponentialSmoothing(
        ts,
        trend="add",
        seasonal="add",
        seasonal_periods=24,
        initialization_method="estimated",
    ).fit(optimized=True, use_brute=False)
    aic = float(hw_full.aic)

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    idx = pd.date_range(start=now + timedelta(hours=1), periods=FORECAST_HORIZON, freq="h")

    future_pred = hw_full.forecast(FORECAST_HORIZON)
    future_pred.index = idx

    forecast_temps = forecast_temperatures(df, FORECAST_HORIZON)
    temp_factors = np.array([temperature_factor(t) for t in forecast_temps])
    adjusted_pred = future_pred.values * temp_factors

    peak_info = analyze_peaks(adjusted_pred, idx)

    forecast_df = pd.DataFrame({
        "station_id": [station_id] * len(idx),
        "timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "predicted_load_kw": np.round(adjusted_pred, 2),
        "mae": np.round(mae, 3),
        "aic": np.round(aic, 2),
    })
    save_forecast(forecast_df)

    return forecast_df, mae, sse, peak_info


def analyze_peaks(predictions: np.ndarray, timestamps) -> dict:
    pred_max = float(np.max(predictions))
    pred_mean = float(np.mean(predictions))
    peak_hours = [int(t.strftime("%H")) for t, v in zip(timestamps, predictions)
                  if v > pred_mean * 1.3]

    return {
        "predicted_max_kw": round(pred_max, 2),
        "predicted_mean_kw": round(pred_mean, 2),
        "peak_hours": peak_hours[:5],
        "is_peak_expected": bool(pred_max > pred_mean * 1.3),
        "peak_severity": round(pred_max / pred_mean - 1.0, 3) if pred_mean > 0 else 0,
    }


def temperature_factor(temp_c: float) -> float:
    if temp_c < 5.0:
        factor = 1.0 + 0.25 * max(0.0, (5.0 - temp_c) / 25.0)
    elif temp_c <= 20.0:
        factor = 1.0 + 0.05 * max(0.0, (20.0 - temp_c) / 15.0)
    elif temp_c <= 30.0:
        factor = 1.0
    else:
        factor = 1.0 + 0.10 * min(1.0, (temp_c - 30.0) / 10.0)
    return round(factor, 4)


def forecast_temperatures(df: pd.DataFrame, horizon: int) -> np.ndarray:
    if 'temperature' not in df.columns or df['temperature'].isna().all():
        return np.full(horizon, 15.0)

    recent_temps = df['temperature'].dropna().tail(48)
    base_temp = float(recent_temps.mean())
    amplitude = float(recent_temps.std()) if len(recent_temps) > 1 else 5.0

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    temps = []
    for h in range(1, horizon + 1):
        future_hour = (now + timedelta(hours=h)).hour
        temp = base_temp + amplitude * np.sin(2 * np.pi * (future_hour - 4) / 24)
        temps.append(round(temp, 1))
    return np.array(temps)
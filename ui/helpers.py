import pandas as pd
import streamlit as st

from config import BASE_TARIFF_RUB
from database import (
    add_log,
    get_history,
    get_stations_info,
    get_tariffs,
    get_user_by_id,
    retrain_forecasts_for_stations,
)
from optimizer import get_current_station_loads, optimize_load
from session_store import (
    clear_session_from_disk,
    load_session_from_disk,
    save_session_to_disk,
)


def get_status_color(ratio, is_active=True):
    if not is_active:
        return [128, 128, 128]
    if ratio < 0.4:
        return [40, 167, 69]
    elif ratio < 0.7:
        return [255, 193, 7]
    else:
        return [220, 53, 69]


def get_current_load_data():
    stations_df = get_stations_info()
    hist = get_history()
    tariffs = get_tariffs()

    if not hist.empty:
        hist["timestamp"] = pd.to_datetime(hist["timestamp"])
        hist_latest = hist.sort_values("timestamp").groupby("station_id").last().reset_index()
        hist_data = hist_latest[["station_id", "load_kw"]].copy()
    else:
        hist_data = pd.DataFrame(columns=["station_id", "load_kw"])

    if not tariffs.empty:
        tariffs["timestamp"] = pd.to_datetime(tariffs["timestamp"])
        tariff_latest = tariffs.sort_values("timestamp").groupby("station_id").last().reset_index()
        tariff_data = tariff_latest[["station_id", "tariff_multiplier", "new_price"]].copy()
        source = "optimization"
    else:
        tariff_data = pd.DataFrame(columns=["station_id", "tariff_multiplier", "new_price"])
        source = "history"

    merged = stations_df.merge(hist_data, left_on="id", right_on="station_id", how="left")

    if not tariff_data.empty:
        merged = merged.merge(tariff_data, left_on="id", right_on="station_id", how="left", suffixes=('', '_t'))

    merged['load_kw'] = merged['load_kw'].fillna(0)
    merged['multiplier'] = merged.get('tariff_multiplier', pd.Series([1.0] * len(merged))).fillna(1.0)
    merged['price'] = merged.get('new_price', pd.Series([BASE_TARIFF_RUB] * len(merged))).fillna(BASE_TARIFF_RUB)

    if 'tariff_multiplier' in merged.columns:
        merged['multiplier'] = merged['tariff_multiplier'].fillna(1.0)
    if 'new_price' in merged.columns:
        merged['price'] = merged['new_price'].fillna(BASE_TARIFF_RUB)

    return merged, stations_df, source


def get_best_station(load_data: pd.DataFrame, active_counts: dict, user_connector: str = None) -> dict | None:
    if load_data is None or load_data.empty:
        return None
    candidates = []
    max_price = load_data['price'].max() or BASE_TARIFF_RUB

    for _, row in load_data.iterrows():
        sid = int(row['id'])
        if not row.get('is_active', True):
            continue
        station_connector = row.get('connector_type', 'CCS')
        if user_connector and station_connector and user_connector != station_connector:
            continue
        slots_left = 5 - active_counts.get(sid, 0)
        if slots_left <= 0:
            continue
        ratio = row['load_kw'] / row['max_power_kw'] if row['max_power_kw'] > 0 else 0
        price_norm = row['price'] / max_price if max_price > 0 else 1.0
        score = (1 - ratio) * 0.5 + (1 - price_norm) * 0.3 + (slots_left / 5) * 0.2
        candidates.append({
            "id": sid,
            "name": row['name'],
            "location": row['location'],
            "price": row['price'],
            "ratio": ratio,
            "slots_left": slots_left,
            "score": score
        })

    if not candidates:
        return None
    return max(candidates, key=lambda x: x['score'])


def calculate_total_load():
    load_df = get_current_station_loads()
    if load_df is None or load_df.empty:
        return 0.0, "none"
    active_load = load_df[load_df.get('is_active', True) == True]['current_load'].sum()
    return active_load, "optimization"


def do_optimize():
    try:
        optimize_load()
        stations = get_stations_info()
        retrained = retrain_forecasts_for_stations(stations['id'].tolist(), min_hours_since_retrain=12)
        if retrained:
            add_log("SYSTEM", f"Переобучены прогнозы для {len(retrained)} станций",
                   f"Станции: {retrained}")
    except Exception as e:
        print(f"[optimize] {e}")


def restore_session():
    if st.session_state.get("logged_in"):
        return
    data = load_session_from_disk()
    if not data:
        return
    try:
        role = data.get("role", "user")
        if role == "admin":
            st.session_state.logged_in = True
            st.session_state.current_user = {
                "id": 0, "username": "admin", "role": "admin"
            }
        else:
            user = get_user_by_id(int(data["id"]))
            if user:
                st.session_state.logged_in = True
                st.session_state.current_user = user
            else:
                clear_session_from_disk()
    except Exception:
        clear_session_from_disk()


def save_session(user: dict):
    save_session_to_disk(user)


def clear_session():
    clear_session_from_disk()
    st.session_state.logged_in = False
    st.session_state.current_user = None

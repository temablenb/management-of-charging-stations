import pandas as pd
import pulp
from database import get_stations_info, save_tariffs, get_history, add_log, get_forecasts
from config import SUBSTATION_LIMIT_KW, BASE_TARIFF_RUB, TARIFF_MIN_MULT, TARIFF_MAX_MULT
from datetime import datetime


def get_current_station_loads() -> pd.DataFrame:
    stations_df = get_stations_info()
    hist = get_history()
    if hist.empty:
        stations_df['current_load'] = stations_df['max_power_kw'] * 0.10
        return stations_df

    hist["timestamp"] = pd.to_datetime(hist["timestamp"])
    now = pd.Timestamp.now()
    recent = hist[hist["timestamp"] >= now - pd.Timedelta(hours=2)]
    source = recent if not recent.empty else hist

    latest = source.sort_values("timestamp").groupby("station_id").last().reset_index()
    merged = stations_df.merge(
        latest[["station_id", "load_kw"]],
        left_on="id", right_on="station_id", how="left"
    )
    merged['current_load'] = merged['load_kw'].fillna(merged['max_power_kw'] * 0.10)
    return merged


def get_expected_peak_load(station_id: int, hours_ahead: int = 6) -> dict:
    fc = get_forecasts(station_id)
    if fc.empty:
        return {"max_kw": 0.0, "mean_kw": 0.0, "peak_hours": [], "has_forecast": False}

    fc["timestamp"] = pd.to_datetime(fc["timestamp"])
    now = pd.Timestamp.now()
    future = fc[fc["timestamp"] > now].head(hours_ahead)

    if future.empty:
        return {"max_kw": 0.0, "mean_kw": 0.0, "peak_hours": [], "has_forecast": False}

    avg_load = float(future["predicted_load_kw"].mean())
    peak_rows = future[future["predicted_load_kw"] > avg_load * 1.3]
    peak_hours = pd.to_datetime(peak_rows["timestamp"]).dt.hour.tolist()

    return {
        "max_kw": float(future["predicted_load_kw"].max()),
        "mean_kw": avg_load,
        "peak_hours": sorted(set(peak_hours))[:5],
        "has_forecast": True,
    }


def calc_tariff_mult(demand_ratio: float, network_ratio: float, forecast_pressure: float = 0.0, curtailment_penalty: float = 0.0) -> float:
    if demand_ratio < 0.30:
        m = TARIFF_MIN_MULT + (1.0 - TARIFF_MIN_MULT) * (demand_ratio / 0.30)
    elif demand_ratio < 0.70:
        m = 1.0 + 0.3 * ((demand_ratio - 0.30) / 0.40)
    else:
        m = 1.3 + (TARIFF_MAX_MULT - 1.3) * ((demand_ratio - 0.70) / 0.30)

    if network_ratio > 0.85:
        m += 0.2 * ((network_ratio - 0.85) / 0.15)
    elif network_ratio < 0.30:
        m -= 0.1

    m += forecast_pressure * 0.3

    m += curtailment_penalty * 0.4

    return round(max(TARIFF_MIN_MULT, min(m, TARIFF_MAX_MULT)), 3)


def optimize_load() -> list:
    use_forecast = True
    load_df = get_current_station_loads()
    if load_df.empty:
        raise RuntimeError("Нет данных о станциях.")

    stations = load_df['id'].tolist()
    n = len(stations)
    total_demand = load_df['current_load'].sum()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    station_names = {int(row['id']): row['name'] for _, row in load_df.iterrows()}

    forecast_info = {}
    expected_total_peak = 0.0
    if use_forecast:
        for _, row in load_df.iterrows():
            sid = int(row['id'])
            fc = get_expected_peak_load(sid)
            forecast_info[sid] = fc
            if fc["has_forecast"] and fc["max_kw"] > 0:
                expected_total_peak += fc["max_kw"]

    total_for_network = max(total_demand, expected_total_peak) if use_forecast else total_demand
    network_ratio = total_for_network / SUBSTATION_LIMIT_KW if SUBSTATION_LIMIT_KW > 0 else 0

    if total_demand < 0.5 and expected_total_peak < 0.5:
        records = []
        for _, row in load_df.iterrows():
            base = float(row['max_power_kw']) * 0.10
            m = calc_tariff_mult(0.10, network_ratio)
            records.append((int(row['id']), now_str, round(base, 2), m, round(m * BASE_TARIFF_RUB, 2)))
        save_tariffs(records)
        add_log("OPTIMIZATION", "Оптимизация: нагрузка близка к нулю",
                f"Станций: {len(records)}", level="WARNING")
        return records

    prob = pulp.LpProblem("EV_Network_Optimizer", pulp.LpMaximize)

    P = {s: pulp.LpVariable(f"P_{s}", lowBound=0) for s in stations}

    prob += pulp.lpSum(P[s] for s in stations)

    prob += pulp.lpSum(P[s] for s in stations) <= SUBSTATION_LIMIT_KW, "SubstationLimit"

    for _, row in load_df.iterrows():
        s = int(row['id'])
        demand = float(row['current_load'])
        max_pw = float(row['max_power_kw'])

        prob += P[s] <= max_pw, f"PhysicalLimit_{s}"
        prob += P[s] <= demand, f"DemandCap_{s}"
        prob += P[s] >= demand * 0.6, f"ServiceQuality_{s}"

    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=20))

    if pulp.LpStatus[prob.status] != "Optimal":
        add_log("OPTIMIZATION", "LP не сошёлся",
                f"Статус: {pulp.LpStatus[prob.status]}", level="WARNING")
        return fallback_optimize(load_df, forecast_info, network_ratio, now_str)

    records = []
    for _, row in load_df.iterrows():
        s = int(row['id'])
        p_opt = round(max(0.0, pulp.value(P[s]) or 0.0), 2)
        demand = float(row['current_load'])
        max_pw = float(row['max_power_kw'])
        demand_ratio = max(0.0, min(demand / max_pw if max_pw > 0 else 0, 1.0))

        curtailment_ratio = 0.0
        if demand > 0:
            curtailment_ratio = max(0.0, 1.0 - (p_opt / demand))

        forecast_pressure = 0.0
        if use_forecast:
            fc = forecast_info.get(s, {})
            if fc.get("has_forecast") and fc.get("max_kw", 0) > 0 and max_pw > 0:
                predicted_ratio = fc["max_kw"] / max_pw
                if predicted_ratio > 0.70:
                    forecast_pressure = min(1.0, (predicted_ratio - 0.70) / 0.30)

        m_opt = calc_tariff_mult(demand_ratio, network_ratio, forecast_pressure, curtailment_ratio)
        price = round(m_opt * BASE_TARIFF_RUB, 2)
        records.append((s, now_str, p_opt, m_opt, price))

    save_tariffs(records)

    total_allocated = sum(r[2] for r in records)
    avg_tariff = sum(r[3] for r in records) / len(records)
    max_rec = max(records, key=lambda r: r[3])
    min_rec = min(records, key=lambda r: r[3])

    details = (
        f"Станций: {len(records)}, "
        f"Выделено всего: {total_allocated:.1f} кВт, "
        f"Средний тариф: {avg_tariff:.3f}x, "
        f"Макс тариф: {max_rec[3]:.3f}x ({station_names.get(max_rec[0])}), "
        f"Мин тариф: {min_rec[3]:.3f}x ({station_names.get(min_rec[0])}), "
        f"Нагрузка сети: {network_ratio * 100:.1f}%, "
        f"Ожидаемый пик (прогноз): {expected_total_peak:.1f} кВт"
    )
    add_log("OPTIMIZATION",
            f"Оптимизация. Текущая: {total_demand:.1f} кВт, "
            f"ожидаемый пик: {expected_total_peak:.1f} кВт",
            details)

    return records


def fallback_optimize(load_df: pd.DataFrame, forecast_info: dict,
                       network_ratio: float, now_str: str) -> list:
    total_demand = load_df['current_load'].sum()
    records = []
    for _, row in load_df.iterrows():
        s = int(row['id'])
        demand = float(row['current_load'])
        max_pw = float(row['max_power_kw'])
        share = demand / total_demand if total_demand > 0 else 1.0 / len(load_df)
        p_opt = round(min(share * SUBSTATION_LIMIT_KW, demand), 2)

        demand_ratio = max(0.0, min(demand / max_pw if max_pw > 0 else 0, 1.0))

        curtailment_ratio = max(0.0, 1.0 - (p_opt / demand)) if demand > 0 else 0.0

        forecast_pressure = 0.0
        fc = forecast_info.get(s, {})
        if fc.get("has_forecast") and fc.get("max_kw", 0) > 0 and max_pw > 0:
            predicted_ratio = fc["max_kw"] / max_pw
            if predicted_ratio > 0.70:
                forecast_pressure = min(1.0, (predicted_ratio - 0.70) / 0.30)

        m_opt = calc_tariff_mult(demand_ratio, network_ratio, forecast_pressure, curtailment_ratio)
        price = round(m_opt * BASE_TARIFF_RUB, 2)
        records.append((s, now_str, p_opt, m_opt, price))

    save_tariffs(records)
    add_log("OPTIMIZATION", "Фолбек-оптимизация",
            f"Нагрузка: {total_demand:.1f} кВт", level="WARNING")
    return records


def get_optimization_summary() -> dict:
    load_df = get_current_station_loads()
    total_demand = load_df['current_load'].sum()
    network_ratio = total_demand / SUBSTATION_LIMIT_KW
    return {
        "total_demand_kw": round(total_demand, 1),
        "network_load_pct": round(network_ratio * 100, 1),
        "substation_limit_kw": SUBSTATION_LIMIT_KW,
        "headroom_kw": round(SUBSTATION_LIMIT_KW - total_demand, 1),
        "stations_count": len(load_df),
        "overloaded": total_demand > SUBSTATION_LIMIT_KW,
    }